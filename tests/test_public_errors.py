"""P1-32 (2026-09-29): nothing internal reaches a caller through the hosted server.

Hosted, "Could not reach the Baseline API at http://127.0.0.1:5050/api/context. Is the server
running? (...)" handed callers an internal address and raw exception text. The API's error bodies
were relayed verbatim too; they are now fixed text for 5xx, and anything relayed is scrubbed."""
import httpx
import pytest

import baseline_mcp.server as srv


class _Resp:
    def __init__(self, status, body, ctype="application/json"):
        self.status_code, self._body, self.text = status, body, str(body)
        self.headers = {"content-type": ctype}

    def json(self):
        if isinstance(self._body, dict):
            return self._body
        raise ValueError("not json")


def _raises(monkeypatch, exc=None, resp=None):
    def post(*a, **k):
        if exc:
            raise exc
        return resp
    monkeypatch.setattr(srv.httpx, "post", post)
    with pytest.raises(RuntimeError) as e:
        srv._post("/api/context", {"query": "x"})
    return str(e.value)


def test_hosted_unreachable_names_no_address(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", True)
    msg = _raises(monkeypatch, exc=httpx.ConnectError("[Errno 111] Connection refused"))
    assert "127.0.0.1" not in msg and "Errno" not in msg and "http" not in msg
    assert "couldn't be reached" in msg


def test_hosted_timeout_names_no_address(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", True)
    msg = _raises(monkeypatch, exc=httpx.ReadTimeout("timed out"))
    assert "127.0.0.1" not in msg and "http" not in msg


def test_local_unreachable_still_names_the_users_own_setting(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", False)
    msg = _raises(monkeypatch, exc=httpx.ConnectError("[Errno 111] Connection refused"))
    assert srv.BASELINE_API_URL in msg and "Errno" not in msg


def test_a_relayed_error_is_scrubbed(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", False)
    msg = _raises(monkeypatch, resp=_Resp(400, {"error": "bad for url: https://x.example/y?apikey=SECRETSECRET /opt/baseline/app.py"}))
    assert "SECRETSECRET" not in msg and "x.example" not in msg and "/opt/" not in msg


def test_an_html_error_page_is_not_relayed(monkeypatch):
    monkeypatch.setattr(srv, "_REMOTE", False)
    msg = _raises(monkeypatch, resp=_Resp(502, "<html><body>502 Bad Gateway nginx</body></html>", "text/html"))
    assert "<html" not in msg and "nginx" not in msg
