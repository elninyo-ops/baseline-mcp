"""Baseline MCP server.

Thin translation layer between the MCP protocol and the Baseline HTTP API.
Contains zero Baseline logic — every tool is a POST to the Baseline API and
a reformat of the JSON response into agent-readable text. If a feature needs
new climate logic, it belongs in Baseline, not here.

See baseline_mcp_server_plan.md (companion doc, in the Baseline project dir)
for the full design rationale.
"""

import concurrent.futures
import contextvars
import functools
import json
import os
import re
import threading
from datetime import datetime

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

BASELINE_API_URL = os.environ.get("BASELINE_API_URL", "http://127.0.0.1:5050").rstrip("/")
BASELINE_API_KEY = os.environ.get("BASELINE_API_KEY", "")

# Documented cold start is 8-12s on the production Droplet (local tile cache).
# 60s gives real margin above that without leaving a genuinely-hung API pending forever.
REQUEST_TIMEOUT_SECONDS = 60.0

# /api/compare processes locations serially server-side (2026-07-26 fix: the
# prior max_workers=2 caused thread oversubscription against each location's
# own internal 10-way tile-loading pool and was measured *slower* than serial
# -- 56s vs 33s for 3 cold locations). Cold-start cost still scales roughly
# linearly with location count (~10s/location), so a full 10-location cold
# category can still take ~100s+; this timeout keeps real margin above that.
COMPARE_TIMEOUT_SECONDS = 240.0

_PROVENANCE_LINE = (
    "Source: Baseline | ERA5-Land reanalysis 1991-2025 (35-yr daily climatology, "
    "WMO 1991-2020 normals), 0.1-degree resolution, land-only | Forecast: Open-Meteo"
)

# The seasonal outlook comes from somewhere else entirely, and the line above would
# misattribute it: no ERA5-Land, no Open-Meteo, a different forecast system and different
# verifying observations per variable. A provenance line that names the wrong sources is
# worse than none, because it reads as precision.
_SEASONAL_PROVENANCE_LINE = (
    "Source: Baseline | Seasonal outlook: ECMWF SEAS5 (system 51), calibrated per box "
    "against 1981-2016 observations | Verified against GHCN_CAMS (temperature) and CPC "
    "Global Unified gauge analysis (precipitation) | Recent-record figures: ERA5-Land"
)

mcp = FastMCP("Baseline")


# --- Daily quota (2026-09-24) ---------------------------------------------------------------
# Every API response to a limited key carries X-RateLimit-* headers. Each tool result ends with
# a line about the allowance when it matters: once on the first call this process makes (so a
# new user learns the limit before meeting it), whenever less than 10% is left, and on the 429.
# The owner's own key once hit the wall with no warning at all; that must never happen to a user.
# Reset times are shown in this machine's local time -- the connector runs on the user's own
# computer, which is the one place that knows their time zone.
_LOW_QUOTA_FRACTION = 0.10
_call_quota: contextvars.ContextVar = contextvars.ContextVar("baseline_quota", default=None)
_intro_lock = threading.Lock()
_intro_shown = False


def _quota_from_headers(headers) -> dict | None:
    try:
        return {"limit": int(headers["X-RateLimit-Limit"]),
                "remaining": int(headers["X-RateLimit-Remaining"]),
                "reset_at": headers.get("X-RateLimit-Reset-At")}
    except (KeyError, TypeError, ValueError):
        return None  # an unlimited key, or an older server: nothing to say


def _local_reset(reset_at: str | None, now: datetime | None = None) -> str:
    """'6:00 PM MDT today (in 8 h 12 min)' -- the UTC reset in the user's own time."""
    try:
        reset = datetime.fromisoformat(reset_at).astimezone()
    except (TypeError, ValueError):
        return "at midnight UTC"
    now = (now or datetime.now()).astimezone()
    clock = reset.strftime("%I:%M %p").lstrip("0")
    days = (reset.date() - now.date()).days
    day = {0: "today", 1: "tomorrow"}.get(days, reset.strftime("%A"))
    minutes = max(int((reset - now).total_seconds() // 60), 0)
    wait = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
    return f"at {clock} {reset.tzname()} {day} (in {wait})"


def _quota_note(quota: dict | None, first_call: bool) -> str:
    if not quota:
        return ""
    limit, remaining = quota["limit"], quota["remaining"]
    when = _local_reset(quota["reset_at"])
    if remaining == 0:
        return (f"Baseline quota: that was the last of today's {limit} questions on this key. "
                f"It resets {when}. Tell the user.")
    if remaining < limit * _LOW_QUOTA_FRACTION:
        return (f"Baseline quota: {remaining} of {limit} questions left today on this key; "
                f"resets {when}. Tell the user.")
    if first_call:
        return (f"Baseline quota: this key allows {limit} questions a day, and {remaining} are "
                f"left today. The count resets {when}. Mention this to the user once.")
    return ""


def _with_quota_note(tool):
    """Append the quota line to a tool's result. Wraps the tool itself so every path out of it,
    error strings included, gets the line."""
    @functools.wraps(tool)
    def wrapper(*args, **kwargs):
        global _intro_shown
        token = _call_quota.set(None)
        try:
            result = tool(*args, **kwargs)
            quota = _call_quota.get()
        finally:
            _call_quota.reset(token)
        with _intro_lock:
            first_call = quota is not None and not _intro_shown
            if first_call:
                _intro_shown = True
        note = _quota_note(quota, first_call)
        return f"{result}\n\n{note}" if note else result
    return wrapper


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
    quota = _quota_from_headers(response.headers)
    if quota:
        _call_quota.set(quota)
    if response.status_code == 429:
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        _call_quota.set(None)  # the message below says it all; no second quota line
        if "lookup_limit" in body:
            raise RuntimeError(
                f"Baseline's daily limit of {body['lookup_limit']} place lookups is used up for "
                f"this key. It resets {_local_reset(body.get('reset_at'))}. Tell the user."
            )
        raise RuntimeError(
            f"Baseline's daily limit of {body.get('daily_limit')} questions is used up for this "
            f"key. It resets {_local_reset(body.get('reset_at'))}. Nothing is wrong with the "
            "question: ask again after the reset. Tell the user."
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


def _assessment_lines(data: dict) -> list:
    """Baseline's own assessment, surfaced ABOVE the raw JSON rather than left inside it.

    Work plan B3: where Baseline did not state its own confidence, the model filled the
    gap with speculation -- including claims that were wrong, one disagreement recycled
    across four unrelated answers, and reflexive "check the station" advice where nothing
    indicated a problem. A field buried in a JSON block does not prevent that; a labelled
    instruction might.

    Shared by both formatters. It used to live inside the context formatter only, and the
    seasonal responses need it MORE, not less -- their caveats are the difference between
    an honest outlook and a forecast claim.
    """
    assessment = data.get("assessment") or {}
    if not assessment.get("headline"):
        return []
    lines = ["\nBaseline Climate's own assessment — relay this, do not compose your own:",
             f"- {assessment['headline']}"]
    keep = assessment.get("if_shortened_keep")
    if keep and keep != assessment["headline"]:
        lines.append(f"- If you shorten it, keep this much intact: {keep}")
    for claim in assessment.get("must_not_claim") or []:
        lines.append(f"- This result does NOT support: {claim}")
    return lines


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

    # Baseline's own assessment, surfaced ABOVE the raw JSON rather than left inside it.
    # Work plan B3: where Baseline did not state its own confidence, the model filled the
    # gap with speculation -- including claims that were wrong, one disagreement recycled
    # across four unrelated answers, and reflexive "check the station" advice where nothing
    # indicated a problem. A field buried in a JSON block does not prevent that; a labelled
    # instruction might.
    lines.extend(_assessment_lines(data))

    lines.append(f"\n{_PROVENANCE_LINE}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
@_with_quota_note
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

    It also answers SEASONAL (three-month) outlook questions, which are about the
    season ahead rather than the next ten days:
    - "Will this season be warmer/wetter than normal in LOCATION?"
    - "Will this winter/spring/summer/fall be warm and wet in LOCATION?"

    Seasonal answers carry a per-location skill label and sometimes say that no
    outlook is currently issued, which is a correct answer rather than a failure —
    see get_seasonal_outlook, which takes a place and variables directly and is the
    better choice when the question is plainly about the season ahead.

    Baseline Climate states its own confidence in an `assessment` field. Relay
    `assessment.headline` as given. If you shorten it, keep
    `assessment.if_shortened_keep` intact — it carries the qualifier, and dropping
    it turns a qualified statement into an unqualified one. Do not compose your own
    assessment of how reliable a result is, do not carry a caveat from one location
    or period to another, and do not add reliability warnings unless the response
    flags a problem. `assessment.must_not_claim` lists what the result does not
    support.
    """
    try:
        data = _post_context({"query": query})
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "clarification_needed":
        return _format_clarification(data)

    return _format_context_result(data)


@mcp.tool()
@_with_quota_note
def get_context_for_coordinates(latitude: float, longitude: float, label: str = "") -> str:
    """Get 10-day forecast and 35-year historical climate context for exact
    coordinates. Use when you have a specific latitude/longitude (a
    property, field, trailhead, or site) rather than a place name — this
    skips geocoding entirely. Land locations only.

    Baseline Climate states its own confidence in an `assessment` field. Relay
    `assessment.headline` as given. If you shorten it, keep
    `assessment.if_shortened_keep` intact — it carries the qualifier, and dropping
    it turns a qualified statement into an unqualified one. Do not compose your own
    assessment of how reliable a result is, do not carry a caveat from one location
    or period to another, and do not add reliability warnings unless the response
    flags a problem. `assessment.must_not_claim` lists what the result does not
    support.
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
@_with_quota_note
def get_water_year_status(location: str) -> str:
    """Get water year precipitation and temperature status for a location:
    totals since the start of the water/calendar year (Oct 1 for North
    America, Jan 1 elsewhere), percentile rank against the same period
    across 35 historical years, and whether conditions are notably wet,
    dry, warm, or cold. Built for drought monitoring, water resource,
    agricultural, and fire-planning contexts. location can be a place name
    ("Casper WY") or "lat,lon" coordinates.

    Baseline Climate states its own confidence in an `assessment` field. Relay
    `assessment.headline` as given. If you shorten it, keep
    `assessment.if_shortened_keep` intact — it carries the qualifier, and dropping
    it turns a qualified statement into an unqualified one. Do not compose your own
    assessment of how reliable a result is, do not carry a caveat from one location
    or period to another, and do not add reliability warnings unless the response
    flags a problem. `assessment.must_not_claim` lists what the result does not
    support.
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
@_with_quota_note
def compare_to_normal(location: str, variable: str, time_window: str = "") -> str:
    """Compare the forecast for the next few days at a location to 35-year
    historical normals. Returns percentile rankings, not vague comparisons.
    Use for questions like "is this week unusually warm" or "will this
    weekend be wetter than normal". The forecast reaches 10 days ahead, so
    time_window must be near-term: a window further out ("this month",
    "this winter") is declined, and a past period ("last month", "this
    water year") is a question for get_climate_context instead.
    variable must be "temperature" or "precipitation". time_window is
    optional free text for a near-term window (e.g. "today", "tomorrow",
    "this weekend", "this week", "the next 10 days") — defaults to
    "this week".

    Baseline Climate states its own confidence in an `assessment` field. Relay
    `assessment.headline` as given. If you shorten it, keep
    `assessment.if_shortened_keep` intact — it carries the qualifier, and dropping
    it turns a qualified statement into an unqualified one. Do not compose your own
    assessment of how reliable a result is, do not carry a caveat from one location
    or period to another, and do not add reliability warnings unless the response
    flags a problem. `assessment.must_not_claim` lists what the result does not
    support.
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
        # rank (group position, e.g. "4") and rank_label (this location's own
        # all-time percentile, e.g. "least snowy") are two independent
        # rankings -- rendering them on the same line ("4. ... -- least
        # snowy") reads as directly contradictory. Split rank_label onto its
        # own indented line so it can't be read as a continuation of the
        # numbered group ranking.
        if entry.get("percent_of_normal") is not None:
            lines.append(
                f"{rank}. {label}: {value} ({entry['percent_of_normal']}% of normal)"
            )
        else:
            lines.append(
                f"{rank}. {label}: {value} ({entry.get('departure_display')} vs. normal)"
            )
        if rank_label:
            lines.append(f"   Historically: {rank_label} on record here")

    lines.append(f"\n{comparison.get('provenance', _PROVENANCE_LINE)}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
@_with_quota_note
def compare_locations(
    locations: list[str] | None = None,
    category: str = "",
    variable: str = "precipitation",
    period: str = "water_year",
    season: str = "",
    year: int = 0,
    month: int = 0,
) -> str:
    """Compare precipitation, temperature, or snowfall across 2-10 locations
    in a single ranked comparison, computed directly by Baseline. Use this
    instead of calling get_climate_context or get_water_year_status once per
    location and comparing the answers yourself — the ranking and
    percent-of-normal figures in the result come from Baseline, not from
    your own arithmetic over several separate answers.

    Provide EITHER `locations` (a list of 2-10 place names and/or "lat,lon"
    strings) OR `category` (a curated group name) — not both.

    Valid category values: colorado_ski_resorts, wyoming_ski_resorts,
    utah_ski_resorts, wyoming_watersheds, colorado_river_basin_states,
    great_plains_ag, major_us_cities, major_european_cities,
    us_national_parks.

    variable: "precipitation" (default), "temperature", or "snowfall".
    Snowfall is sourced from a different, coarser (0.25-degree) Open-Meteo
    archive than precipitation/temperature (0.1-degree ERA5-Land) — results
    are correct but not directly resolution-comparable across variables.

    period: "water_year" (default, Oct 1 / Jan 1 to date), "season" (also
    set season="winter"/"spring"/"summer"/"fall" and optionally year),
    "month" (also set month=1-12 and optionally year), or "ski_season"
    (fixed Nov 1 - Apr 30 window; optionally set year=<November's year>,
    e.g. year=2019 for the 2019-2020 season; defaults to the most recently
    started ski season). Custom date ranges are not supported — use
    "water_year", "season", "month", or "ski_season".
    """
    if locations and category:
        return "Provide either locations or category, not both."
    if not locations and not category:
        return "Provide either locations (2-10 places) or category (a curated group name)."

    payload: dict = {"variable": variable, "period": period}
    if period == "season":
        if not season:
            return "period='season' requires season to be set (winter/spring/summer/fall)."
        payload["season"] = season
        if year:
            payload["year"] = year
    elif period == "month":
        if not month:
            return "period='month' requires month to be set (1-12)."
        payload["month"] = month
        if year:
            payload["year"] = year
    elif period == "ski_season":
        if year:
            payload["year"] = year

    if category:
        payload["category"] = category
    else:
        if len(locations) < 2 or len(locations) > 10:
            return f"locations must have between 2 and 10 entries (got {len(locations)})."
        # Resolved in parallel, not sequentially — with several free-text
        # locations this used to pay N round-trips end to end even though
        # each resolve is independent. Errors are reported in list order
        # (not first-to-finish) so the result is deterministic.
        resolved: list[dict | None] = [None] * len(locations)
        errors: list[str | None] = [None] * len(locations)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(locations), 5)) as executor:
            futures = {
                executor.submit(_resolve_location, text): i
                for i, text in enumerate(locations)
            }
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    resolved[i] = future.result()
                except RuntimeError as error:
                    errors[i] = str(error)
        first_error = next((error for error in errors if error is not None), None)
        if first_error:
            return first_error
        payload["locations"] = resolved

    try:
        data = _post("/api/compare", payload, timeout=COMPARE_TIMEOUT_SECONDS)
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "error":
        return data.get("error", "Unknown error from Baseline API.")

    return _format_compare_result(data)


def _format_seasonal_result(data: dict) -> str:
    lines = []
    loc = data.get("location") or {}
    if loc.get("name"):
        lines.append(f"Location: {loc['name']}")
    season = data.get("season")
    variables = data.get("variables") or ([data["variable"]] if data.get("variable") else [])
    if season:
        lines.append(f"Season: {season}   Variables: {', '.join(variables)}")

    short_answer = data.get("short_answer") or {}
    if short_answer.get("answer"):
        lines.append(f"\nSeasonal outlook: {short_answer['answer']}")
        if short_answer.get("confidence"):
            lines.append(f"\nConfidence: {short_answer['confidence']}")

    # The skill label per variable, named rather than left for the model to infer from prose.
    for variable in variables:
        block = (data.get("by_variable") or {}).get(variable) or data
        skill = block.get("skill") or {}
        if skill.get("status"):
            lines.append(f"- {variable}: skill status {skill['status']}")

    lines.extend(_assessment_lines(data))
    lines.append(f"\n{_SEASONAL_PROVENANCE_LINE}")
    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")
    return "\n".join(lines)


@mcp.tool()
@_with_quota_note
def get_seasonal_outlook(
    location: str,
    variables: list[str] | None = None,
    season: str = "",
) -> str:
    """Seasonal (three-month) outlook for a location: calibrated probabilities that the
    season will be below, near or above normal, for temperature, precipitation, or both.

    This is a three-month climate outlook, not a weather forecast. For conditions over the
    next ten days, or for how unusual recent weather has been, use get_climate_context.

    location: a place name ("Harare", "Denver, Colorado") or a "lat,lon" string.
    variables: any of "temperature", "precipitation". Defaults to BOTH, which answers
        compound questions like "will this winter be warm and wet" in one call — ask for
        both rather than calling twice and stitching the answers together.
    season: optional "DJF", "MAM", "JJA" or "SON". Leave empty for the season currently
        being forecast, which is almost always what a question about "this season" means.

    WHAT YOU GET BACK, AND HOW IT VARIES BY PLACE:

    Probabilities are produced for every land location the model covers, and they are
    always returned. How well they have been tested is a separate matter that varies by
    location and season: at some places the odds have been shown to beat a climatological
    guess, at some only the direction is worth using, at some a simple warming trend
    predicted the season better than the model did, and at many they have never been
    tested at all. The answer states which of these applies in its own words. Relay that
    standing as written — an untested outlook is not a bad one, and neither is it a
    verified one.

    "NO OUTLOOK IS CURRENTLY ISSUED" IS A NORMAL, CORRECT ANSWER. An outlook exists only
    for the forecast cycle now live, which is the season the models have most recently
    been run for. Ask in September about the coming December-February and the honest reply
    is that none is issued yet, because the forecast it would be built from has not been
    produced. That is expected behaviour, not a failure, a gap in coverage or a reason to
    retry: relay it as given, and say when the outlook will be published if the response
    says so. Do not substitute a forecast, a historical average or your own estimate.

    Some answers say the forecast is more extreme than anything in the years the model was
    fitted on, and that the odds are held at the strongest the record supports. This is
    common rather than exotic — it applies to about a third of locations on the current
    cycle and to most tropical ones. Keep that sentence; it is the difference between a
    bounded estimate and an invented one.

    Baseline Climate states its own confidence in an `assessment` field. Relay
    `assessment.headline` as given. If you shorten it, keep `assessment.if_shortened_keep`
    intact — it carries the qualifier, and for a two-variable answer it carries one for
    each half, so dropping part of it turns a qualified statement into an unqualified one.
    Do not compose your own assessment of how reliable a result is, and do not carry a
    caveat from one location or season to another.
    """
    wanted = [v.strip().lower() for v in (variables or ["temperature", "precipitation"])
              if v and v.strip()]
    if not wanted:
        wanted = ["temperature", "precipitation"]
    unknown = [v for v in wanted if v not in ("temperature", "precipitation")]
    if unknown:
        return (f"Unknown variable(s): {', '.join(unknown)}. "
                f"This tool covers temperature and precipitation.")

    try:
        place = _resolve_location(location)
    except RuntimeError as error:
        return str(error)

    payload = {"lat": place["lat"], "lon": place["lon"],
               "label": place.get("label") or location,
               "variables": list(dict.fromkeys(wanted))}
    if season:
        payload["season"] = season.strip().upper()

    try:
        data = _post("/api/seasonal-outlook", payload)
    except RuntimeError as error:
        return str(error)

    return _format_seasonal_result(data)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
