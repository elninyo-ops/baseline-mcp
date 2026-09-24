"""The connector tells the user about the daily quota before they hit it, not only after.

    python3 tests/test_quota_notes.py      # no pytest needed
    pytest tests/                          # if you have it

Every test drives a real tool through a fake httpx.post, so what's checked is the tool result
the agent sees, not a helper in isolation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

import baseline_mcp.server as server

RESET_AT = (datetime.now(timezone.utc) + timedelta(hours=5)).replace(microsecond=0).isoformat()
OK_BODY = {"status": "ok", "summary": "It was dry.", "location_name": "Casper"}


def _response(status: int, remaining: int | None, limit: int = 100, body: dict | None = None):
    headers = {"content-type": "application/json"}
    if remaining is not None:
        headers.update({"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining),
                        "X-RateLimit-Reset-At": RESET_AT})
    return httpx.Response(status, json=body if body is not None else OK_BODY, headers=headers,
                          request=httpx.Request("POST", "http://test"))


def _ask(*responses) -> list[str]:
    """Run get_climate_context once per response, in a fresh connector process state."""
    queue = list(responses)
    real_post = httpx.post
    httpx.post = lambda *a, **k: queue.pop(0)
    server._intro_shown = False
    try:
        return [server.get_climate_context("Has Casper, WY been dry this year?") for _ in responses]
    finally:
        httpx.post = real_post


def test_the_first_call_states_the_limit_and_later_calls_stay_quiet():
    first, second = _ask(_response(200, 99), _response(200, 98))
    assert "this key allows 100 questions a day, and 99 are left today" in first
    assert "Baseline quota" not in second


def test_under_ten_percent_every_call_warns():
    results = _ask(_response(200, 50), _response(200, 10), _response(200, 9), _response(200, 1))
    assert "Baseline quota" not in results[1]          # 10 of 100 is not under 10%
    assert "9 of 100 questions left today" in results[2]
    assert "1 of 100 questions left today" in results[3]


def test_the_last_question_says_so():
    (result,) = _ask(_response(200, 0))
    assert "that was the last of today's 100 questions" in result


def test_the_limit_itself_says_when_it_resets_in_local_time_and_nothing_else():
    body = {"error": "Rate limit exceeded", "daily_limit": 100, "remaining": 0, "reset_at": RESET_AT}
    (result,) = _ask(_response(429, 0, body=body))
    local = datetime.fromisoformat(RESET_AT).astimezone()
    assert "daily limit of 100 questions is used up" in result
    assert local.strftime("%I:%M %p").lstrip("0") in result and local.tzname() in result
    assert result.count("Baseline quota") == 0


def test_an_unlimited_key_hears_nothing():
    first, second = _ask(_response(200, None), _response(200, None))
    assert "quota" not in first.lower() and "quota" not in second.lower()


def test_the_local_reset_names_the_day_and_the_wait():
    now = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
    text = server._local_reset("2026-09-25T00:00:00+00:00", now=now)
    assert "(in 9 h 0 min)" in text
    assert server._local_reset("garbage") == "at midnight UTC"


def test_every_tool_carries_the_quota_line():
    """A tool added later without the wrapper would be the one path that never warns."""
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) >= 6
    unwrapped = [t.name for t in tools if t.fn.__code__ is not server._with_quota_note(lambda: 0).__code__]
    assert unwrapped == []


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} passed")
