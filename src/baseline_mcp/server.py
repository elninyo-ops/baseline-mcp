"""Baseline MCP server.

Thin translation layer between the MCP protocol and the Baseline HTTP API.
Contains zero Baseline logic — every tool is a POST to the Baseline API and
a reformat of the JSON response into agent-readable text. If a feature needs
new climate logic, it belongs in Baseline, not here.

See baseline_mcp_server_plan.md (companion doc, in the Baseline project dir)
for the full design rationale.
"""

import json
import os
import re

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

BASELINE_API_URL = os.environ.get("BASELINE_API_URL", "http://127.0.0.1:5050").rstrip("/")
BASELINE_API_KEY = os.environ.get("BASELINE_API_KEY", "")

# Documented cold start is 8-12s on the production Droplet (local tile cache).
# 60s gives real margin above that without leaving a genuinely-hung API pending forever.
REQUEST_TIMEOUT_SECONDS = 60.0

_PROVENANCE_LINE = (
    "Source: Baseline | ERA5-Land reanalysis 1991-2025 (35-yr daily climatology, "
    "WMO 1991-2020 normals), 0.1-degree resolution, land-only | Forecast: Open-Meteo"
)

mcp = FastMCP("Baseline")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if BASELINE_API_KEY:
        headers["X-Api-Key"] = BASELINE_API_KEY
    return headers


def _post_context(payload: dict) -> dict:
    """POST to Baseline's /api/context. Raises RuntimeError with an actionable
    message on any failure — callers should catch this and hand it back to the
    agent as the tool result, not let it surface as a stack trace."""
    url = f"{BASELINE_API_URL}/api/context"
    try:
        response = httpx.post(url, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.ConnectError as error:
        raise RuntimeError(
            f"Could not reach the Baseline API at {url}. Is the server running? ({error})"
        )
    except httpx.TimeoutException:
        raise RuntimeError(f"Baseline API at {url} timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s.")

    if response.status_code == 401:
        raise RuntimeError(
            "Baseline API rejected the request (401 Unauthorized). "
            "Check that BASELINE_API_KEY is set and valid."
        )
    if response.status_code == 429:
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        raise RuntimeError(
            f"Baseline API rate limit exceeded (daily_limit={body.get('daily_limit')}, "
            f"resets at {body.get('reset_at')})."
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Baseline API returned {response.status_code}: {detail}")

    return response.json()


def _format_clarification(data: dict) -> str:
    question = data.get("question", "The location is ambiguous.")
    candidates = data.get("candidates") or []
    lines = [question, ""]
    for c in candidates:
        label = c.get("label") or c.get("name") or "Unknown"
        lat, lon = c.get("lat"), c.get("lon")
        if lat is not None and lon is not None:
            lines.append(f"- {label} ({lat}, {lon})")
        else:
            lines.append(f"- {label}")
    lines.append("")
    lines.append(
        "Call this tool again with a more specific location string, or with "
        "exact coordinates, to resolve the ambiguity."
    )
    return "\n".join(lines)


def _format_context_result(data: dict) -> str:
    lines = []

    location_name = data.get("location_name")
    if location_name:
        lines.append(f"Location: {location_name}")

    short_answer = data.get("short_answer") or {}
    if short_answer.get("show"):
        title = short_answer.get("title") or "Short Answer"
        answer = short_answer.get("answer") or ""
        lines.append(f"\n{title}: {answer}")

    summary = data.get("summary")
    if summary:
        lines.append(f"\nOverview: {summary}")

    water_year_context = data.get("water_year_context")
    if water_year_context:
        lines.append(f"\n{water_year_context}")

    metrics = data.get("metrics") or []
    if metrics:
        lines.append("\nKey signals:")
        for metric in metrics[:6]:
            label = metric.get("label") if isinstance(metric, dict) else None
            value = metric.get("value") if isinstance(metric, dict) else None
            if label is not None:
                lines.append(f"- {label}: {value}")

    lines.append(f"\n{_PROVENANCE_LINE}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
def get_climate_context(query: str) -> str:
    """Get statistically rigorous weather and climate context for any location
    on Earth (land only). Answers natural-language questions with 10-day
    forecast data and historical percentile rankings against a 35-year ERA5
    daily climatology (1991-2025, WMO 1991-2020 normals). Use this when you
    need to know not just what conditions are or will be, but how unusual
    they are relative to history.

    query MUST be phrased as a question in one of these forms (the location
    goes where LOCATION is shown; the underlying parser matches these
    patterns specifically and will fail on other phrasings, e.g. "weather
    context for LOCATION" does not work):
    - "Will LOCATION be warmer/wetter than normal this week?"
    - "Has LOCATION been dry this water year?" / "this year?"
    - "How cold/warm/wet was last winter/spring/summer/fall in LOCATION?"
    - "What is the wettest/driest month in LOCATION?"
    """
    try:
        data = _post_context({"query": query})
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "clarification_needed":
        return _format_clarification(data)

    return _format_context_result(data)


@mcp.tool()
def get_context_for_coordinates(latitude: float, longitude: float, label: str = "") -> str:
    """Get 10-day forecast and 35-year historical climate context for exact
    coordinates. Use when you have a specific latitude/longitude (a
    property, field, trailhead, or site) rather than a place name — this
    skips geocoding entirely. Land locations only.
    """
    location_explicit = {"lat": latitude, "lon": longitude}
    if label:
        location_explicit["label"] = label

    try:
        data = _post_context({"location_explicit": location_explicit})
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "clarification_needed":
        return _format_clarification(data)

    return _format_context_result(data)


_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _parse_coords(text: str):
    match = _COORD_RE.match(text)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


@mcp.tool()
def get_water_year_status(location: str) -> str:
    """Get water year precipitation and temperature status for a location:
    totals since the start of the water/calendar year (Oct 1 for North
    America, Jan 1 elsewhere), percentile rank against the same period
    across 35 historical years, and whether conditions are notably wet,
    dry, warm, or cold. Built for drought monitoring, water resource,
    agricultural, and fire-planning contexts. location can be a place name
    ("Casper WY") or "lat,lon" coordinates.
    """
    coords = _parse_coords(location)
    if coords:
        lat, lon = coords
        payload = {
            "location_explicit": {"lat": lat, "lon": lon, "label": location},
            "query": "Has this location been dry this water year?",
        }
    else:
        payload = {"query": f"Has {location} been dry this water year?"}

    try:
        data = _post_context(payload)
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "clarification_needed":
        return _format_clarification(data)

    return _format_context_result(data)


@mcp.tool()
def compare_to_normal(location: str, variable: str, time_window: str = "") -> str:
    """Compare current or forecast conditions at a location to 35-year
    historical normals. Returns percentile rankings, not vague comparisons.
    Use for questions like "is this week unusually warm" or "will it be
    wetter than normal this month". variable must be "temperature" or
    "precipitation". time_window is optional free text (e.g. "this week",
    "this month") — defaults to "this week".
    """
    variable = variable.strip().lower()
    if variable not in ("temperature", "precipitation"):
        return f'variable must be "temperature" or "precipitation" (got {variable!r}).'

    adjective = "warmer" if variable == "temperature" else "wetter"
    window = time_window.strip() or "this week"
    query = f"Will {location} be {adjective} than normal {window}?"

    try:
        data = _post_context({"query": query})
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "clarification_needed":
        return _format_clarification(data)

    return _format_context_result(data)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
