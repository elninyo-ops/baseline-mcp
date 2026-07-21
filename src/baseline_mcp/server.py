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

# /api/compare processes up to 10 locations at 2 concurrent workers server-side, so its
# cold-start cost is not the single-location figure above — measured 2:57 for a cold
# 10-location call in dev. This is a real latency problem (see baseline_mcp_server_plan.md
# follow-up), not something to treat as settled; the longer timeout here just keeps the
# tool from failing outright on large categories until that gets fixed.
COMPARE_TIMEOUT_SECONDS = 240.0

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


def _post(path: str, payload: dict, timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict:
    """POST to a Baseline API path. Raises RuntimeError with an actionable
    message on any failure — callers should catch this and hand it back to the
    agent as the tool result, not let it surface as a stack trace."""
    url = f"{BASELINE_API_URL}{path}"
    try:
        response = httpx.post(url, json=payload, headers=_headers(), timeout=timeout)
    except httpx.ConnectError as error:
        raise RuntimeError(
            f"Could not reach the Baseline API at {url}. Is the server running? ({error})"
        )
    except httpx.TimeoutException:
        raise RuntimeError(f"Baseline API at {url} timed out after {timeout:.0f}s.")

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


def _post_context(payload: dict) -> dict:
    return _post("/api/context", payload)


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


def _resolve_location(text: str) -> dict:
    """Resolve a place name or 'lat,lon' string to {lat, lon, label} via
    Baseline's /api/resolve. Raises RuntimeError on failure or ambiguity."""
    coords = _parse_coords(text)
    if coords:
        lat, lon = coords
        return {"lat": lat, "lon": lon, "label": text}

    data = _post("/api/resolve", {"location": text})

    if data.get("status") == "ambiguous":
        candidates = ", ".join(
            c.get("label") or c.get("name", "?") for c in data.get("candidates", [])
        )
        raise RuntimeError(
            f"{text!r} is ambiguous. Candidates: {candidates}. "
            "Use a more specific name or exact coordinates."
        )

    return {"lat": data["lat"], "lon": data["lon"], "label": data.get("name", text)}


def _format_compare_result(data: dict) -> str:
    comparison = data.get("comparison", {})
    lines = [
        f"Compared {comparison.get('n_locations')} locations — "
        f"{comparison.get('variable_label')}, {comparison.get('period_label')} "
        f"(vs. {comparison.get('baseline_years')} baseline)",
        "",
    ]

    for entry in comparison.get("ranked", []):
        label = entry.get("label", "Unknown")
        if entry.get("status") not in ("ok", "partial"):
            lines.append(f"- {label}: no data ({entry.get('reason', 'unknown error')})")
            continue

        rank = entry.get("rank")
        value = entry.get("value_display")
        rank_label = entry.get("rank_label", "")
        if entry.get("percent_of_normal") is not None:
            lines.append(
                f"{rank}. {label}: {value} ({entry['percent_of_normal']}% of normal) — {rank_label}"
            )
        else:
            lines.append(
                f"{rank}. {label}: {value} ({entry.get('departure_display')} vs. normal) — {rank_label}"
            )

    lines.append(f"\n{_PROVENANCE_LINE}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
def compare_locations(
    locations: list[str] | None = None,
    category: str = "",
    variable: str = "precipitation",
    period: str = "water_year",
    season: str = "",
    year: int = 0,
    month: int = 0,
) -> str:
    """Compare precipitation or temperature across 2-10 locations in a single
    ranked comparison, computed directly by Baseline. Use this instead of
    calling get_climate_context or get_water_year_status once per location
    and comparing the answers yourself — the ranking and percent-of-normal
    figures in the result come from Baseline, not from your own arithmetic
    over several separate answers.

    Provide EITHER `locations` (a list of 2-10 place names and/or "lat,lon"
    strings) OR `category` (a curated group name) — not both.

    Valid category values: colorado_ski_resorts, wyoming_ski_resorts,
    utah_ski_resorts, wyoming_watersheds, colorado_river_basin_states,
    great_plains_ag, major_us_cities, major_european_cities,
    us_national_parks.

    variable: "precipitation" (default) or "temperature".
    period: "water_year" (default, Oct 1 / Jan 1 to date), "season" (also
    set season="winter"/"spring"/"summer"/"fall" and optionally year), or
    "month" (also set month=1-12 and optionally year). Custom date ranges
    are not supported by this tool — use "water_year", "season", or "month".
    """
    if locations and category:
        return "Provide either locations or category, not both."
    if not locations and not category:
        return "Provide either locations (2-10 places) or category (a curated group name)."

    payload: dict = {"variable": variable, "period": period}
    if season:
        payload["season"] = season
    if year:
        payload["year"] = year
    if month:
        payload["month"] = month

    if category:
        payload["category"] = category
    else:
        if len(locations) < 2 or len(locations) > 10:
            return f"locations must have between 2 and 10 entries (got {len(locations)})."
        resolved = []
        for text in locations:
            try:
                resolved.append(_resolve_location(text))
            except RuntimeError as error:
                return str(error)
        payload["locations"] = resolved

    try:
        data = _post("/api/compare", payload, timeout=COMPARE_TIMEOUT_SECONDS)
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "error":
        return data.get("error", "Unknown error from Baseline API.")

    return _format_compare_result(data)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
