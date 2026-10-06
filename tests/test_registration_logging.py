"""The refused-registration alert, part 1 (baseline repo, docs/phase2_design_2026-10-01.md §17.16): one JSON
line on stderr per 401 challenge and per first verified token, by client_id, which the baseline repo's
tools/registration_alert.py counts. Never the token, never an email, never the user id."""
import io
import json
import re
import time

import pytest

from baseline_mcp import oauth
from test_oauth_wiring import ACCT, call, on, token  # noqa: F401  (the fixture `on` is used by name)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(oauth, "_SEEN_CLIENTS", set())


def events(capsys):
    out = []
    for line in capsys.readouterr().err.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and str(obj.get("event", "")).startswith("oauth_"):
            out.append(obj)
    return out


def test_a_challenge_without_a_credential_is_logged(on, monkeypatch, capsys):
    assert call("/mcp", {}, monkeypatch)[0] == 401
    (e,) = events(capsys)
    assert e["event"] == "oauth_challenge" and e["reason"] == "no_credential" and e["client_id"] is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\dZ", e["ts"])          # to the minute, no finer


def test_the_first_token_from_a_client_is_logged_once(on, monkeypatch, capsys):
    t = token()
    for _ in range(3):
        assert call("/mcp", {"authorization": f"Bearer {t}"}, monkeypatch)[0] == 200
    assert call("/mcp", {"authorization": f"Bearer {token(client_id='client-xyz')}"}, monkeypatch)[0] == 200
    got = events(capsys)
    assert [(e["event"], e["client_id"]) for e in got] == [("oauth_token_first", "client-abc"),
                                                           ("oauth_token_first", "client-xyz")]


def test_a_token_whose_account_is_not_synced_still_counts_as_a_token(on, monkeypatch, capsys):
    # Registration and sign-in worked; the account copy is just behind (503). That is not a refusal.
    t = token(sub="user-unknown", iat=int(time.time()) - 30)
    assert call("/mcp", {"authorization": f"Bearer {t}"}, monkeypatch)[0] == 503
    assert [e["event"] for e in events(capsys)] == ["oauth_token_first"]


def test_a_refused_token_is_a_challenge_with_its_claimed_client(on, monkeypatch, capsys):
    t = token(exp=int(time.time()) - 10)
    assert call("/mcp", {"authorization": f"Bearer {t}"}, monkeypatch)[0] == 401
    (e,) = events(capsys)
    assert e == {"event": "oauth_challenge", "client_id": "client-abc", "ts": e["ts"], "reason": "invalid_token"}


def test_no_token_email_or_user_id_reaches_the_log(on, monkeypatch, capsys):
    good, expired = token(email="someone@example.com"), token(exp=int(time.time()) - 10, email="x@example.com")
    call("/mcp", {"authorization": f"Bearer {good}"}, monkeypatch)
    call("/mcp", {"authorization": f"Bearer {expired}"}, monkeypatch)
    call("/mcp", {}, monkeypatch)
    captured = capsys.readouterr()
    text = captured.err + captured.out
    assert '"oauth_token_first"' in text and '"oauth_challenge"' in text
    for secret in (good, expired, "@example.com", "user-1", ACCT):
        assert secret not in text
    for part in good.split("."):
        assert part not in text


def test_a_strange_client_id_is_dropped_not_logged():
    buf = io.StringIO()
    oauth.log_event("oauth_challenge", 'x"\n{"event":"oauth_token_first"}', "invalid_token", stream=buf)
    assert buf.getvalue().count("\n") == 1 and json.loads(buf.getvalue())["client_id"] is None


def test_while_off_nothing_is_logged(monkeypatch, capsys):
    monkeypatch.setattr(oauth, "ISSUER", "")
    call("/mcp", {}, monkeypatch)
    assert events(capsys) == []
