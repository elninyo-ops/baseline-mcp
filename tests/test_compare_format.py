"""How compare results read (P1-14, P1-15; 2026-09-26): ties, withheld ranks, near-tie notes."""

from baseline_mcp.server import _format_compare_result


def _text(ranked, **comparison):
    data = {"comparison": {"n_locations": len(ranked), "variable_label": "Snowfall",
                           "period_label": "Ski Season 2025-26", "baseline_years": "1991–2025",
                           "provenance": "p", "ranked": ranked, **comparison}}
    return _format_compare_result(data).split("\n```json")[0]


def test_a_tie_shares_the_position_and_names_the_other_location():
    text = _text([
        {"label": "Breckenridge", "status": "ok", "rank": 5, "value_display": "56.9 in",
         "percent_of_normal": 66.0, "tied_with": ["Keystone"]},
        {"label": "Keystone", "status": "ok", "rank": 5, "value_display": "56.9 in",
         "percent_of_normal": 66.0, "tied_with": ["Breckenridge"]},
    ])
    assert "5= Breckenridge: 56.9 in (66.0% of normal, tied with Keystone)" in text
    assert "5= Keystone: 56.9 in (66.0% of normal, tied with Breckenridge)" in text
    assert not [l for l in text.splitlines() if l.startswith("6")]


def test_a_withheld_comparison_shows_the_value_alone():
    text = _text([{"label": "Casper, WY", "status": "partial", "rank": 1, "value_display": "0.79 in",
                   "comparison_withheld": True}], confidence="low")
    assert "1. Casper, WY: 0.79 in\n" in text + "\n"
    assert "None" not in text
    assert "Historically" not in text
    assert "Confidence: low" in text


def test_the_near_tie_note_follows_the_historical_rank():
    text = _text([{"label": "Casper, WY", "status": "ok", "rank": 1, "value_display": "9.61 in",
                   "percent_of_normal": 64.0, "rank_label": "driest",
                   "rank_cluster_note": "it's within 0.08 in of the 2nd driest year"}])
    assert ("Historically: driest on record here — though it's within 0.08 in of the 2nd driest year"
            in text)


def test_no_group_position_when_the_server_withheld_it():
    text = _text([{"label": "A", "status": "partial", "rank": None, "value_display": "9.61 in",
                   "percent_of_normal": 64.0}])
    assert "- A: 9.61 in (64.0% of normal)" in text
    assert "None" not in text


def test_a_suppressed_percent_of_normal_no_longer_prints_none():
    text = _text([{"label": "A", "status": "ok", "rank": 1, "value_display": "0.02 in",
                   "percent_of_normal": None, "rank_label": "driest"}])
    assert "None" not in text
    assert "1. A: 0.02 in\n" in text


def test_a_rows_notes_print_under_it():
    """2026-09-29: a far record cell or corrected rainfall is stated on the row, not only in the JSON."""
    note = "The nearest land in Baseline's record is 40 miles south of Galveston; these figures are for that point."
    text = _text([
        {"label": "Galveston", "status": "ok", "rank": 1, "value_display": "40.1 in", "percent_of_normal": 90.0,
         "rank_label": "near average", "notes": [note]},
        {"label": "Houston", "status": "ok", "rank": 2, "value_display": "38.0 in", "percent_of_normal": 85.0},
    ])
    lines = text.splitlines()
    i = lines.index("1. Galveston: 40.1 in (90.0% of normal)")
    assert lines[i + 2] == f"   Note: {note}"
    assert "Note:" not in "\n".join(lines[i + 3:])


def test_the_partial_period_note_is_printed():
    text = _text([{"label": "Casper, WY", "status": "partial", "rank": 1, "value_display": "9.1 in",
                   "percent_of_normal": 70.0}],
                 coverage_note="The record covers 335 of the 360 days asked about.", confidence="low")
    assert "The record covers 335 of the 360 days asked about." in text
