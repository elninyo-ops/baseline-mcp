"""OAuth on the hosted MCP (design: baseline repo, docs/phase2_design_2026-10-01.md §13.2-13.3; route
"Supabase alone", decided 2026-10-02; built per the owner's decision of 2026-10-05, §17.20 D).

The account is the identity and the meter; a key or a token is only a credential (§13.2):
- a bearer JWT is verified here (Supabase's published keys, cached; issuer; expiry; audience
  "authenticated"; issued to an OAuth client, i.e. it carries client_id), and its `sub` is mapped to an
  account through the API droplet's local accounts copy;
- the MCP then calls the API with ITS OWN service key plus X-Baseline-Account. The token never leaves
  the MCP (the spec forbids passing it through);
- no credential at all gets a 401 whose WWW-Authenticate points at the Protected Resource Metadata,
  which is what starts sign-in in Claude and ChatGPT;
- Baseline keys (bl_...) keep working exactly as before (§13.3).

Nothing here is on unless BASELINE_OAUTH_ISSUER is set, so today's key-only server is unchanged until
the owner turns it on (the dashboard checklist in the baseline repo's review queue).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from functools import lru_cache

ISSUER = os.environ.get("BASELINE_OAUTH_ISSUER", "").rstrip("/")             # https://<ref>.supabase.co/auth/v1
JWKS_URL = os.environ.get("BASELINE_OAUTH_JWKS_URL", "") or (f"{ISSUER}/.well-known/jwks.json" if ISSUER else "")
RESOURCE = os.environ.get("BASELINE_MCP_RESOURCE_URL", "https://mcp.baselinecontext.com/mcp")
METADATA_PATH = "/.well-known/oauth-protected-resource"
ACCOUNTS_PATH = os.environ.get("BASELINE_ACCOUNTS_PATH", "/opt/baseline/accounts.json")
SERVICE_KEY = os.environ.get("BASELINE_MCP_SERVICE_KEY", "")
AUDIENCE = "authenticated"                      # Supabase sets this on every access token (§13.1)
SCOPES = ["openid", "email", "profile", "offline_access"]
NEW_ACCOUNT_GRACE_SECONDS = 600                 # a token minted this recently whose account isn't synced: 503


def enabled() -> bool:
    return bool(ISSUER and SERVICE_KEY)


def looks_like_jwt(credential: str) -> bool:
    return credential.count(".") == 2 and not credential.startswith("bl_")


def metadata_url() -> str:
    base = RESOURCE.split("/", 3)
    return f"{base[0]}//{base[2]}{METADATA_PATH}"


def protected_resource_metadata() -> dict:
    """RFC 9728 metadata: which authorization server issues tokens for this MCP."""
    return {"resource": RESOURCE, "authorization_servers": [ISSUER], "scopes_supported": SCOPES,
            "bearer_methods_supported": ["header"], "resource_name": "Baseline"}


def www_authenticate(error: str | None = None) -> str:
    value = f'Bearer resource_metadata="{metadata_url()}"'
    return value + (f', error="{error}"' if error else "")


class TokenRejected(Exception):
    def __init__(self, status: int, message: str, error: str = "invalid_token"):
        super().__init__(message)
        self.status, self.message, self.error = status, message, error


@lru_cache(maxsize=1)
def _jwks_client():
    import jwt
    return jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


def verify(token: str) -> dict:
    """The token's claims, or TokenRejected."""
    import jwt
    try:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256"], audience=AUDIENCE, issuer=ISSUER,
                            options={"require": ["exp", "sub", "iss"]})
    except jwt.ExpiredSignatureError:
        raise TokenRejected(401, "The sign-in has expired. Sign in again.")
    except jwt.PyJWTError:
        raise TokenRejected(401, "That sign-in token is not valid.")
    if not claims.get("client_id"):
        # The web app's own sessions carry no client_id: only tokens issued to an OAuth client are for us.
        raise TokenRejected(401, "That token was not issued for the Baseline connector.")
    return claims


_ACCOUNTS = {"mtime": None, "by_user": {}}


def _accounts_by_user() -> dict:
    try:
        mtime = os.stat(ACCOUNTS_PATH).st_mtime_ns
    except FileNotFoundError:
        return {}
    if mtime != _ACCOUNTS["mtime"]:
        with open(ACCOUNTS_PATH) as fh:
            data = json.load(fh)
        _ACCOUNTS["by_user"] = {v.get("auth_user_id"): (k, v) for k, v in data.items() if v.get("auth_user_id")}
        _ACCOUNTS["mtime"] = mtime
    return _ACCOUNTS["by_user"]


def account_for(claims: dict, now: float | None = None) -> str:
    """The account id for a verified token's user, or TokenRejected (401 deleted or off; 503 too new)."""
    hit = _accounts_by_user().get(claims["sub"])
    if hit is None:
        if (now or time.time()) - float(claims.get("iat") or 0) < NEW_ACCOUNT_GRACE_SECONDS:
            raise TokenRejected(503, "Your account is being set up. Try again in a minute.", "temporarily_unavailable")
        raise TokenRejected(401, "No Baseline account matches this sign-in.")
    account_id, acct = hit
    if not acct.get("api_active", True):
        raise TokenRejected(401, "This account has no active access.")
    return account_id


# The refused-registration alert, part 1 (baseline repo, docs/phase2_design_2026-10-01.md §17.16): one
# JSON line on stderr (so in the MCP's journal) per 401 challenge and per first request that arrives
# with a verified token, by client_id. tools/registration_alert.py in the baseline repo reads the last
# 10 minutes every 5 and alerts when many challenges lead to few tokens: a client that can't register
# never gets a token. Never the token, never an email, never the user id: event, client_id, minute.
CHALLENGE_EVENT = "oauth_challenge"
FIRST_TOKEN_EVENT = "oauth_token_first"
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_SEEN_CLIENTS: set = set()
_SEEN_CLIENTS_MAX = 50_000                      # forgotten wholesale past this: a client logs "first" again


def _minute(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() if now is None else now))


def _safe_client_id(value) -> str | None:
    return value if isinstance(value, str) and _CLIENT_ID.match(value) else None


def unverified_client_id(token: str) -> str | None:
    """The client_id a rejected token claims, for the log only (its signature wasn't checked)."""
    try:
        import jwt
        return _safe_client_id(jwt.decode(token, options={"verify_signature": False}).get("client_id"))
    except Exception:
        return None


def log_event(event: str, client_id: str | None = None, reason: str | None = None,
              now: float | None = None, stream=None) -> None:
    line = {"event": event, "client_id": _safe_client_id(client_id), "ts": _minute(now)}
    if reason:
        line["reason"] = reason
    out = stream or sys.stderr
    out.write(json.dumps(line) + "\n")
    out.flush()


def log_challenge(reason: str, client_id: str | None = None) -> None:
    """A 401 that carries WWW-Authenticate: no credential ("no_credential"), or a refused token."""
    log_event(CHALLENGE_EVENT, client_id, reason)


def log_token_seen(claims: dict) -> None:
    """The first verified token from a client_id since the MCP started."""
    client_id = _safe_client_id(claims.get("client_id"))
    key = client_id or "<unknown>"
    if key in _SEEN_CLIENTS:
        return
    if len(_SEEN_CLIENTS) >= _SEEN_CLIENTS_MAX:
        _SEEN_CLIENTS.clear()
    _SEEN_CLIENTS.add(key)
    log_event(FIRST_TOKEN_EVENT, client_id)
