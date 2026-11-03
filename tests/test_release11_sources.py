"""Release 11 (API repo docs/release_11_rename_design.md §2.3, §2.4): the three formatters print the API's own
`sources` (one builder, in the API, so the two can't disagree): "Data details:" above, then the "Sources:"
line, the station line and the CHIRPS line when present. No "Source: Baseline" line, no "Forecast:
Open-Meteo", and an answer from an API without `sources` gets only the "Full credits" line."""
from __future__ import annotations

from baseline_mcp.server import (FALLBACK_SOURCES_LINE, _format_compare_result, _format_context_result,
                                 _format_seasonal_result)

LINE_P = ("Sources: Contains modified Copernicus Climate Change Service information 2026. ERA5-Land data © ECMWF, "
          "CC BY 4.0, accessed through the Destination Earth Platform. Full credits: https://hoodoowx.com/data-sources")
LINE_O = ("Sources: Contains modified Copernicus Climate Change Service information 2026. ECMWF SEAS5 data © ECMWF, "
          "CC BY 4.0, from the Copernicus Climate Data Store. Full credits: https://hoodoowx.com/data-sources")
DETAILS = "ERA5-Land reanalysis 1991–2025 (34 of 35 years used), WMO 1991–2020 normals, 0.1° grid, land only"
STATIONS = "Station data: NOAA GHCN-Daily; ACIS (NOAA Regional Climate Centers)."
CHIRPS = "Rainfall record: CHIRPS, Climate Hazards Center, UC Santa Barbara."


def _head(text: str) -> str:
    """The printed answer above the JSON block, without the blank line before that block."""
    return text.split("\n```json")[0].rstrip("\n")


def _sources(line, details=None, station_line=None, chirps_line=None):
    return {"line": line, "details": details, "station_line": station_line, "chirps_line": chirps_line}


def test_context_prints_details_then_the_lines_in_order():
    data = {"summary": "Dry.", "sources": _sources(LINE_P, DETAILS, STATIONS)}
    head = _head(_format_context_result(data))
    assert f"\nData details: {DETAILS}\n{LINE_P}\n{STATIONS}" in head
    assert "Source: Baseline" not in head and "Forecast: Open-Meteo" not in head


def test_context_without_sources_prints_only_the_credits_line():
    head = _head(_format_context_result({"summary": "Dry."}))
    assert head.endswith(FALLBACK_SOURCES_LINE)
    assert FALLBACK_SOURCES_LINE == "Sources: Full credits: https://hoodoowx.com/data-sources"
    assert "Data details" not in head and "Source: Baseline" not in head


def test_a_still_working_reply_prints_no_source_line():
    """Owner, 2026-11-03 (release 11 tier 3): the API's 202 "Still working" reply shows no data, so it names no
    source -- neither the old line nor the bare credits line. The answer a minute later carries its own lines."""
    data = {"status": "processing",
            "short_answer": {"show": True, "title": "Still working", "answer": "Still working on this one."},
            "summary": "Still working on this one."}
    head = _head(_format_context_result(data))
    assert "Sources:" not in head and "Data details" not in head and "Source: Baseline" not in head
    assert head.endswith("Overview: Still working on this one.")


def test_compare_prints_the_comparisons_sources():
    data = {"status": "ok", "comparison": {
        "period_label": "Water Year 2026", "n_locations": 1, "variable_label": "Precipitation",
        "baseline_years": "1991–2025", "provenance": "p", "ranked": [],
        "sources": _sources(LINE_P, "ERA5-Land reanalysis 1991-2025, WMO 1991-2020 normals, 0.1-degree resolution")}}
    head = _head(_format_compare_result(data))
    assert head.endswith("\nData details: ERA5-Land reanalysis 1991-2025, WMO 1991-2020 normals, 0.1-degree "
                         "resolution\n" + LINE_P)
    assert "Source: Baseline" not in head


def test_seasonal_prints_its_sources_and_the_chirps_line():
    data = {"short_answer": {"answer": "Leaning wetter."}, "variables": ["precipitation"],
            "sources": _sources(LINE_O, "ECMWF SEAS5 system 51, calibrated per area against 1981–2016 observations",
                                None, CHIRPS)}
    head = _head(_format_seasonal_result(data))
    assert head.endswith(f"\nData details: ECMWF SEAS5 system 51, calibrated per area against 1981–2016 "
                         f"observations\n{LINE_O}\n{CHIRPS}")
    # The calibration datasets go only on the data sources page (owner, 2026-11-03).
    assert "GHCN_CAMS" not in head and "CPC Global Unified" not in head


def test_seasonal_without_sources_prints_only_the_credits_line():
    head = _head(_format_seasonal_result({"short_answer": {"answer": "x"}, "variables": ["precipitation"]}))
    assert head.endswith(FALLBACK_SOURCES_LINE)
