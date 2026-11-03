"""Snowfall in the connector's output (owner, 2026-10-20; API docs/snowfall_discrepancy_2026-10-19.md).

Criteria 3a-3d (the source line names ERA5 via Open-Meteo and the snowfall data's own date; rain and snowfall
together name both) were tests of the connector's own source-line builder. Release 11 removes that builder:
the API builds the line once (source_lines.py) and the connector prints it. Those criteria are now pinned in
the API repo's tests/test_source_lines.py (test_snowfall_and_wind_line_is_the_owners_text,
test_past_with_snowfall_combines_both_records, test_details_name_snowfall_alone_not_wind,
test_details_for_snowfall_only), and the printing here in tests/test_release11_sources.py.
"""
from baseline_mcp.server import _format_compare_result

LABEL = ("Snowfall amounts are model estimates and often run below what stations measure, especially in "
         "mountains; the comparison with normal is more reliable.")


def test_a_snowfall_comparison_prints_the_amounts_label():
    """Criterion 4c: the API sends it; the connector prints it, once."""
    data = {"comparison": {"n_locations": 1, "variable_label": "Snowfall", "period_label": "Ski Season 2005–2006",
                           "baseline_years": "1991–2025", "provenance": "p", "amounts_note": LABEL,
                           "ranked": [{"label": "Vail", "status": "ok", "rank": 1, "value_display": "110 in",
                                       "percent_of_normal": 98.0}]}}
    text = _format_compare_result(data).split("\n```json")[0]
    assert text.count(LABEL) == 1
    assert "110 in" in text
