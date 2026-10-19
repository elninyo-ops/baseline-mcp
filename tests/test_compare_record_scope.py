"""A comparison row says "on record" only when its ranking used the whole record (owner, 2026-10-19).

A leap-year winter was ranked against 9 of the record's 34 winters and printed "Historically: wettest on
record here". The API now sends each row's `rank_scope`: "on record here" when the ranking used every
complete period, otherwise "of the 9 winters compared here — not the full 34-winter record".
"""

from baseline_mcp.server import _format_compare_result


def _text(ranked, **comparison):
    data = {"comparison": {"n_locations": len(ranked), "variable_label": "Precipitation",
                           "period_label": "Winter 2015–2016", "baseline_years": "1991–2025",
                           "provenance": "p", "ranked": ranked, **comparison}}
    return _format_compare_result(data).split("\n```json")[0]


def test_a_short_record_row_never_says_on_record():
    text = _text([{"label": "Tampa", "status": "ok", "rank": 1, "value_display": "9.41 in",
                   "percent_of_normal": 157.0, "rank_label": "wettest", "years_ranked": 9,
                   "years_expected": 34,
                   "rank_scope": "of the 9 winters compared here — not the full 34-winter record",
                   "trust_line": "91 of 91 days · ranked against 9 of 34 winters · ERA5-Land"}],
                 confidence="low")
    assert "on record" not in text
    assert ("Historically: wettest of the 9 winters compared here — not the full 34-winter record"
            in text)
    assert "ranked against 9 of 34 winters" in text
    assert "Confidence: low" in text


def test_a_complete_record_row_says_on_record_here():
    text = _text([{"label": "Tampa", "status": "ok", "rank": 1, "value_display": "16.11 in",
                   "percent_of_normal": 248.0, "rank_label": "wettest", "years_ranked": 34,
                   "years_expected": 34, "rank_scope": "on record here",
                   "rank_cluster_note": "it's within 0.1 in of the 2nd wettest year"}])
    assert ("Historically: wettest on record here — though it's within 0.1 in of the 2nd wettest year"
            in text)
