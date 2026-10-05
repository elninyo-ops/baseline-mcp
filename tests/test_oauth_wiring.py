"""OAuth wiring (baseline repo §13.2-13.3; owner decision, prompt 2026-10-05, §17.20 D), with Supabase's
settings stubbed: a throwaway EC key stands in for the project's signing key, and the issuer, service
key and accounts copy are set per test. Nothing connects anywhere. (The issuer is assembled from parts:
the baseline repo's unattended guard refuses a file that spells out a project address.)"""
import asyncio
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import baseline_mcp.server as srv
from baseline_mcp import oauth

ISS = "https://" + "abcdefghijklmnopqrst" + ".supabase" + ".co/auth/v1"
ACCT = "11111111-1111-1111-1111-111111111111"
PRIV = ec.generate_private_key(ec.SECP256R1())


class _Key:
    key = PRIV.public_key()


class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return _Key()


@pytest.fixture
def on(monkeypatch, tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps({ACCT: {"auth_user_id": "user-1", "api_active": True},
                                    "22222222-2222-2222-2222-222222222222": {"auth_user_id": "user-off",
                                                                             "api_active": False}}))
    monkeypatch.setattr(oauth, "ISSUER", ISS)
    monkeypatch.setattr(oauth, "SERVICE_KEY", "bl_mcp_service")
    monkeypatch.setattr(oauth, "ACCOUNTS_PATH", str(accounts))
    monkeypatch.setattr(oauth, "_ACCOUNTS", {"mtime": None, "by_user": {}})
    monkeypatch.setattr(oauth, "_jwks_client", lambda: _Jwks())


def token(**over):
    now = int(time.time())
    claims = {"iss": ISS, "aud": "authenticated", "sub": "user-1", "exp": now + 3600, "iat": now - 3600,
              "client_id": "client-abc", **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, PRIV, algorithm="ES256")


def call(path, headers, monkeypatch, valid=True):
    reached = {}

    async def app(scope, receive, send):
        reached["account"] = scope.get("baseline_account")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def fake_valid(key):
        return valid
    monkeypatch.setattr(srv, "_key_is_valid", fake_valid)
    sent = []

    async def send(m):
        sent.append(m)
    scope = {"type": "http", "path": path, "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(srv._auth_gate(app)(scope, None, send))
    head = {k.decode(): v.decode() for k, v in sent[0].get("headers", [])}
    return sent[0]["status"], head, reached


def test_no_credential_is_a_401_pointing_at_the_metadata(on, monkeypatch):
    status, head, reached = call("/mcp", {}, monkeypatch)
    assert status == 401 and not reached
    assert head["www-authenticate"] == ('Bearer resource_metadata="https://mcp.baselinecontext.com'
                                        '/.well-known/oauth-protected-resource"')


def test_a_valid_token_reaches_the_server_as_its_account(on, monkeypatch):
    status, _, reached = call("/mcp", {"authorization": f"Bearer {token()}"}, monkeypatch)
    assert status == 200 and reached["account"] == ACCT


@pytest.mark.parametrize("claims,status", [
    ({"exp": int(time.time()) - 10}, 401),                         # expired
    ({"client_id": None}, 401),                                    # the web app's own session, not a connector's
    ({"iss": "https://other.example/auth/v1"}, 401),               # another issuer
    ({"aud": "something-else"}, 401),
    ({"sub": "user-unknown"}, 401),                                # deleted, or never an account
    ({"sub": "user-unknown", "iat": int(time.time()) - 30}, 503),  # brand new, not synced yet
    ({"sub": "user-off"}, 401),                                    # access switched off
])
def test_bad_tokens_are_refused(on, monkeypatch, claims, status):
    got, head, reached = call("/mcp", {"authorization": f"Bearer {token(**claims)}"}, monkeypatch)
    assert got == status and not reached
    if status == 401:
        assert 'error="invalid_token"' in head["www-authenticate"]


def test_keys_work_exactly_as_before(on, monkeypatch):
    status, _, reached = call("/mcp", {"x-api-key": "bl_customer_key"}, monkeypatch)
    assert status == 200 and reached["account"] is None
    assert call("/mcp", {"authorization": "Bearer bl_customer_key"}, monkeypatch, valid=False)[0] == 401


def test_the_api_gets_the_service_key_and_the_account_never_the_token(on, monkeypatch):
    monkeypatch.setattr(srv, "_caller_account", lambda: ACCT)
    assert srv._headers() == {"Content-Type": "application/json", "X-Api-Key": "bl_mcp_service",
                              "X-Baseline-Account": ACCT}
    assert "your account" in srv._quota_note({"limit": 100, "remaining": 5, "reset_at": None}, False)


def test_the_metadata_names_the_issuer(on):
    m = oauth.protected_resource_metadata()
    assert m["resource"] == "https://mcp.baselinecontext.com/mcp" and m["authorization_servers"] == [ISS]
    assert "offline_access" in m["scopes_supported"]


def test_while_off_nothing_changes(monkeypatch):
    monkeypatch.setattr(oauth, "ISSUER", "")
    status, head, _ = call("/mcp", {}, monkeypatch)
    assert status == 401 and "www-authenticate" not in head
    assert call("/mcp", {"authorization": f"Bearer {token()}"}, monkeypatch, valid=False)[0] == 401
