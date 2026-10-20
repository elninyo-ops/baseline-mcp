"""A snowfall answer's source line names where snowfall comes from (owner, 2026-10-20; API docs/
snowfall_discrepancy_2026-10-19.md, criteria 3a-3d and 4c): ERA5 via Open-Meteo at 0.25 degree, with the
snowfall data's own latest date. It used to say "ERA5-Land reanalysis ... 0.1-degree", the rain and
temperature record, which snowfall never came from."""
from baseline_mcp.server import _PROVENANCE_LINE, _format_compare_result, _format_context_result

LABEL = ("Snowfall amounts are model estimates and often run below what stations measure, especially in "
         "mountains; the comparison with normal is more reliable.")


def _source_line(text: str) -> str:
    return next(l for l in text.splitlines() if l.startswith("Source: Baseline"))


def _answer(signals, **freshness):
    return {"short_answer": {"show": True, "title": "Short Answer", "answer": "x"},
            "temporal_stats": {"historical": {"count": 35, "normal_count": 30},
                               "data_freshness": {"baseline_start_year": 1991, "baseline_end_year": 2025,
                                                  "latest_available_date": "2026-09-30", **freshness},
                               "signals": signals}}


def test_a_snowfall_answer_names_era5_via_open_meteo_and_the_snowfall_date():
    """Criterion 3a."""
    data = _answer({"snowfall": {"total_display": "25.9 in"}},
                   snowfall_source="open_meteo_era5_archive_0.25deg", snowfall_latest_available_date="2026-10-12")
    line = _source_line(_format_context_result(data))
    assert "ERA5 via Open-Meteo" in line and "0.25-degree" in line and "2026-10-12" in line
    assert "ERA5-Land" not in line and "2026-09-30" not in line and "0.1-degree" not in line


def test_an_answer_with_snowfall_and_rain_names_both_with_their_own_dates():
    """Criterion 3b."""
    data = _answer({"snowfall": {"total_display": "25.9 in"}, "precipitation": {"total_display": "3 in"}},
                   snowfall_source="open_meteo_era5_archive_0.25deg", snowfall_latest_available_date="2026-10-12")
    line = _source_line(_format_context_result(data))
    assert "ERA5-Land" in line and "2026-09-30" in line
    assert "ERA5 via Open-Meteo" in line and "2026-10-12" in line


def test_an_answer_without_snowfall_keeps_its_line():
    """Criterion 3d."""
    data = _answer({"precipitation": {"total_display": "3 in"}})
    assert _source_line(_format_context_result(data)) == _PROVENANCE_LINE


def test_a_snowfall_comparison_prints_the_amounts_label():
    """Criterion 4c: the API sends it; the connector prints it, once."""
    data = {"comparison": {"n_locations": 1, "variable_label": "Snowfall", "period_label": "Ski Season 2005–2006",
                           "baseline_years": "1991–2025", "provenance": "p", "amounts_note": LABEL,
                           "ranked": [{"label": "Vail", "status": "ok", "rank": 1, "value_display": "110 in",
                                       "percent_of_normal": 98.0}]}}
    text = _format_compare_result(data).split("\n```json")[0]
    assert text.count(LABEL) == 1
    assert "110 in" in text
