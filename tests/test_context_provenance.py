"""The source line under a get_climate_context-style answer says what that answer used (owner, 2026-10-01):
SEAS5 for a seasonal answer, and the real number of years when fewer than 35 were used."""
from baseline_mcp.server import (_PROVENANCE_LINE, _SEASONAL_PROVENANCE_LINE, _format_context_result)


def _source_line(text: str) -> str:
    return next(l for l in text.splitlines() if l.startswith("Source: Baseline"))


def test_a_seasonal_answer_names_the_seasonal_sources():
    data = {"short_answer": {"show": True, "title": "Seasonal Outlook", "answer": "Odds favour wetter."},
            "summary": "Odds favour wetter.", "metrics": [], "days": []}
    assert _source_line(_format_context_result(data)) == _SEASONAL_PROVENANCE_LINE


def test_a_water_year_ranked_against_34_years_says_34():
    data = {"short_answer": {"show": True, "title": "Short Answer", "answer": "2nd driest since 1991."},
            "temporal_stats": {"historical": {"count": 34, "normal_count": 29},
                               "data_freshness": {"baseline_start_year": 1991, "baseline_end_year": 2025}}}
    line = _source_line(_format_context_result(data))
    assert "34 of the 35 years used" in line and "35-yr" not in line


def test_a_forecast_uses_its_fewest_days_count():
    days = [{"signals": {"baseline_record_count": n, "baseline_start_year": 1991, "baseline_end_year": 2025}}
            for n in (35, 33, 35)]
    line = _source_line(_format_context_result({"summary": "x", "days": days}))
    assert "33 of the 35 years used" in line


def test_a_full_record_keeps_the_standard_line():
    days = [{"signals": {"baseline_record_count": 35, "baseline_start_year": 1991, "baseline_end_year": 2025}}]
    assert _source_line(_format_context_result({"summary": "x", "days": days})) == _PROVENANCE_LINE
    assert _source_line(_format_context_result({"summary": "x"})) == _PROVENANCE_LINE
