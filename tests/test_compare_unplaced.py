"""One entry a comparison can't place no longer sinks the rest (owner, 2026-10-01): "Goshen County, WY" in a
list of four failed the whole comparison with "That sounds like an area rather than a single point"."""
import asyncio

import baseline_mcp.server as srv

AREA = "Baseline API returned 400: That sounds like an area rather than a single point. For now, give me a city, landmark, ski resort, or coordinates to use as a representative point."


def _fake_resolve(text):
    if "County" in text:
        raise RuntimeError(AREA)
    return {"lat": 41.0, "lon": -104.0, "label": text}


def _fake_post(path, payload, timeout=None):
    assert path == "/api/compare"
    _fake_post.sent = payload
    return {"status": "ok", "comparison": {"variable": "precipitation", "ranked": [
        {"label": l["label"], "status": "ok", "value_display": "10.0 in", "rank": i + 1}
        for i, l in enumerate(payload["locations"])]}}


def test_the_places_that_resolve_are_compared_and_the_area_is_named_in_words(monkeypatch):
    monkeypatch.setattr(srv, "_resolve_location", _fake_resolve)
    monkeypatch.setattr(srv, "_post", _fake_post)
    out = asyncio.run(srv.compare_locations(locations=["Torrington, WY", "Scottsbluff, NE", "Cheyenne, WY", "Goshen County, WY"],
                                            variable="precipitation", period="water_year"))
    assert [l["label"] for l in _fake_post.sent["locations"]] == ["Torrington, WY", "Scottsbluff, NE", "Cheyenne, WY"]
    assert out.startswith("Left out of the comparison: 1 of the 4 places asked for couldn't be placed.")
    assert "- Goshen County, WY: That sounds like an area rather than a single point." in out
    assert "Baseline API returned" not in out.split("```json")[0] and "400" not in out.split("```json")[0]
    assert "Torrington, WY" in out


def test_fewer_than_two_placed_says_why_no_comparison(monkeypatch):
    monkeypatch.setattr(srv, "_resolve_location", _fake_resolve)
    monkeypatch.setattr(srv, "_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    out = asyncio.run(srv.compare_locations(locations=["Goshen County, WY", "Laramie County, WY", "Cheyenne, WY"],
                                            variable="precipitation", period="water_year"))
    assert out.startswith("No comparison: a comparison needs at least two places")
    assert "- Goshen County, WY: That sounds like an area" in out and "- Laramie County, WY:" in out
