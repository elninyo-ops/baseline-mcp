"""Remote (HTTP) mode, Part D (2026-09-26): the caller's key, the auth gate, the log line."""

import asyncio
import json
import logging

import pytest

import baseline_mcp.server as srv


def test_the_key_comes_from_x_api_key_or_a_bearer_header_only():
    assert srv._key_from_headers({"x-api-key": " k1 "}) == "k1"
    assert srv._key_from_headers({"authorization": "Bearer k2"}) == "k2"
    assert srv._key_from_headers({"authorization": "Basic abc"}) == ""
    assert srv._key_from_headers({}) == ""


def test_a_caller_is_named_by_fingerprint_never_by_key():
    cid = srv._caller_id("secret-key-value")
    assert cid.startswith("sha256:") and len(cid) == len("sha256:") + 10
    assert "secret" not in cid
    assert srv._caller_id("") == "none"


def test_local_mode_still_uses_the_environment_key(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", False)
    monkeypatch.setattr(srv, "BASELINE_API_KEY", "env-key")
    assert srv._headers()["X-Api-Key"] == "env-key"


def test_remote_mode_never_falls_back_to_the_environment_key(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", True)
    monkeypatch.setattr(srv, "BASELINE_API_KEY", "env-key")
    assert "X-Api-Key" not in srv._headers()          # no request context: no key at all


def _call_gate(path, headers, valid=True, monkeypatch=None):
    reached = {}

    async def app(scope, receive, send):
        reached["yes"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def fake_valid(key):
        return valid

    monkeypatch.setattr(srv, "_key_is_valid", fake_valid)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path,
             "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(srv._auth_gate(app)(scope, None, send))
    return sent[0]["status"], (sent[1].get("body") or b"").decode(), reached.get("yes", False)


def test_no_key_is_a_clean_401_before_mcp(monkeypatch):
    status, body, reached = _call_gate("/mcp", {}, monkeypatch=monkeypatch)
    assert status == 401 and not reached
    assert "X-Api-Key" in json.loads(body)["error"]


def test_an_unknown_key_is_a_clean_401(monkeypatch):
    status, body, reached = _call_gate("/mcp", {"x-api-key": "bad"}, valid=False, monkeypatch=monkeypatch)
    assert status == 401 and not reached


def test_the_api_being_down_is_a_503_not_a_502(monkeypatch):
    status, _, reached = _call_gate("/mcp", {"x-api-key": "k"}, valid=None, monkeypatch=monkeypatch)
    assert status == 503 and not reached


def test_a_valid_key_reaches_mcp_and_healthz_needs_none(monkeypatch):
    assert _call_gate("/mcp", {"x-api-key": "k"}, monkeypatch=monkeypatch)[2]
    assert _call_gate("/healthz", {}, valid=False, monkeypatch=monkeypatch)[2]


def test_the_log_line_names_tool_time_status_and_caller_but_no_key_or_arguments(monkeypatch, caplog):
    monkeypatch.setattr(srv, "_REMOTE", False)
    monkeypatch.setattr(srv, "BASELINE_API_KEY", "super-secret-key")

    def tool(query):
        srv._call_status.set("http_429")
        return "limit reached"

    wrapped = srv._logged(tool)
    with caplog.at_level(logging.INFO, logger="baseline_mcp"):
        assert asyncio.run(wrapped("Casper rainfall this week")) == "limit reached"
    line = json.loads(caplog.records[-1].getMessage())
    assert line["tool"] == "tool" and line["status"] == "http_429"
    assert line["caller"] == srv._caller_id("super-secret-key")
    assert isinstance(line["ms"], int)
    text = caplog.records[-1].getMessage()
    assert "super-secret-key" not in text and "Casper" not in text
