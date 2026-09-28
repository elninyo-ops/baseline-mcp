"""P1-31 (2026-09-28): every HTTP request to the hosted server gets one log line -- JSON-RPC method,
protocol-version header, status, and the SDK's message on an error -- through the real MCP SDK app,
since the 400s claude.ai received came from the SDK before any tool ran. Never the params or key."""
import json
import logging

import pytest
from starlette.testclient import TestClient

import baseline_mcp.server as srv

KEY = "test-key-never-logged"
QUESTION = "How wet was August 2026 in Casper, WY?"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", True)

    async def valid(key):
        return True
    monkeypatch.setattr(srv, "_key_is_valid", valid)
    from mcp.server.transport_security import TransportSecuritySettings
    # The production settings from main(): the public host, DNS-rebinding protection on.
    monkeypatch.setattr(srv.mcp.settings, "transport_security", TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=["mcp.baselinecontext.com"],
        allowed_origins=["https://mcp.baselinecontext.com", "https://claude.ai"]))
    monkeypatch.setattr(srv.mcp.settings, "stateless_http", True)
    monkeypatch.setattr(srv.mcp, "_session_manager", None)   # a fresh session manager per test
    app = srv._auth_gate(srv.mcp.streamable_http_app())
    with TestClient(app, base_url="https://mcp.baselinecontext.com") as c:
        yield c


def _post(client, body, pv=None):
    headers = {"X-Api-Key": KEY, "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if pv:
        headers["mcp-protocol-version"] = pv
    return client.post("/mcp", headers=headers, content=json.dumps(body))


def _http_lines(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.name == "baseline_mcp" and '"event": "http"' in r.getMessage()]


def test_an_unsupported_protocol_version_is_logged_with_its_reason(client, caplog):
    with caplog.at_level(logging.INFO, logger="baseline_mcp"):
        r = _post(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, pv="2099-01-01")
    assert r.status_code == 400
    line = _http_lines(caplog)[-1]
    assert line["status"] == 400 and line["rpc"] == ["tools/list"] and line["rpc_id"] == [7]
    assert line["pv"] == "2099-01-01" and line["sid"] is False
    assert "Unsupported protocol version: 2099-01-01" in line["error"]
    assert line["caller"] == srv._caller_id(KEY)


def test_a_normal_request_is_logged_without_its_arguments_or_key(client, caplog):
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_climate_context", "arguments": {"query": QUESTION}}}
    with caplog.at_level(logging.INFO, logger="baseline_mcp"):
        _post(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, pv="2025-06-18")
        _post(client, body, pv="2025-06-18")      # the tool itself fails offline; that's fine
    lines = _http_lines(caplog)
    assert [l["rpc"] for l in lines[-2:]] == [["tools/list"], ["tools/call"]]
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert KEY not in text and QUESTION not in text and "Casper" not in text


def test_an_unparseable_body_is_logged_as_such(client, caplog):
    with caplog.at_level(logging.INFO, logger="baseline_mcp"):
        r = client.post("/mcp", headers={"X-Api-Key": KEY, "Content-Type": "application/json",
                                         "Accept": "application/json, text/event-stream"}, content=b"{not json")
    assert r.status_code == 400
    line = _http_lines(caplog)[-1]
    assert line["rpc"] == ["<unparseable>"] and "Parse error" in line["error"]
