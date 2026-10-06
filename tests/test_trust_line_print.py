"""The trust line is printed directly under the headline, and under every comparison row (owner, 2026-10-02)."""
from baseline_mcp.server import _format_compare_result, _format_context_result, _format_seasonal_result

LINE = "335 of 365 days, through Aug 31 · ranked against 34 years · nearest data point 3.0 mi away · ERA5-Land"


def test_context_answer_prints_the_line_right_under_the_headline():
    text = _format_context_result({"short_answer": {"show": True, "title": "Short Answer", "answer": "2nd driest."},
                                   "summary": "2nd driest.", "trust_line": LINE})
    lines = [l for l in text.split("```json")[0].splitlines() if l.strip()]
    assert lines[lines.index("Short Answer: 2nd driest.") + 1] == LINE


def test_every_comparison_row_prints_its_line_including_rows_without_data():
    data = {"status": "ok", "comparison": {"variable": "precipitation", "period_label": "Water Year 2026", "ranked": [
        {"label": "Topeka KS", "status": "partial", "value_display": "36.60 in", "rank": 1, "rank_label": "near average",
         "trust_line": "335 of 365 days, through Aug 31 · ranked against 34 years · nearest data point 1.9 mi away · ERA5-Land"},
        {"label": "Mid-Pacific", "status": "no_land_near_place", "reason_text": "No land.",
         "trust_line": "no land data at this point · ERA5-Land"}]}}
    text = _format_compare_result(data).split("```json")[0]
    assert "   335 of 365 days, through Aug 31 · ranked against 34 years" in text
    assert "   no land data at this point · ERA5-Land" in text


def test_seasonal_answer_prints_the_line():
    text = _format_seasonal_result({"short_answer": {"answer": "Leaning wetter."}, "variables": ["precipitation"],
                                    "trust_line": "3-month outlook · accuracy not yet checked here · averaged over a 10° by 10° area · ECMWF SEAS5"})
    assert "3-month outlook · accuracy not yet checked here" in text.split("```json")[0]
