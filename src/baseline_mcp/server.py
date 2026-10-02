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
import hashlib
import json
import logging
import os
import re
import threading
import time
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

def _record_years_used(data: dict):
    """(years used, first year, last year) of the record an answer was ranked against, or None.

    A past period carries its count in temporal_stats.historical; a forecast carries one per day
    (the fewest is what the answer can claim). Water Year 1991 starts before the archive does, so a
    water-year answer ranks against 34 years, not 35."""
    ts = data.get("temporal_stats") or {}
    hist, fresh = ts.get("historical") or {}, ts.get("data_freshness") or {}
    if isinstance(hist.get("count"), int):
        return hist["count"], fresh.get("baseline_start_year"), fresh.get("baseline_end_year")
    counts = [((d.get("signals") or {}).get("baseline_record_count"),
               (d.get("signals") or {}).get("baseline_start_year"),
               (d.get("signals") or {}).get("baseline_end_year"))
              for d in data.get("days") or [] if isinstance(d, dict)]
    counts = [c for c in counts if isinstance(c[0], int)]
    return min(counts) if counts else None


def _context_provenance_line(data: dict) -> str:
    """The source line under a context answer, true to what that answer used (owner, 2026-10-01):
    - a seasonal answer (get_climate_context answers those too) names SEAS5, not ERA5-Land/Open-Meteo;
    - the "35-yr" claim becomes the real count when fewer years were used. Unknown: the standard line."""
    if (data.get("short_answer") or {}).get("title") == "Seasonal Outlook":
        return _SEASONAL_PROVENANCE_LINE
    used = _record_years_used(data)
    if used:
        n, start, end = used
        start, end = start or 1991, end or 2025
        span = end - start + 1
        if n < span:
            return (f"Source: Baseline | ERA5-Land reanalysis {start}-{end} ({n} of the {span} years "
                    "used, WMO 1991-2020 normals), 0.1-degree resolution, land-only | Forecast: Open-Meteo")
    return _PROVENANCE_LINE


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
# Callers (by key fingerprint) who have had the first-call quota line. One entry locally; one
# per key when the server is remote and shared.
_intro_shown_for: set = set()


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
        token = _call_quota.set(None)
        try:
            result = tool(*args, **kwargs)
            quota = _call_quota.get()
        finally:
            _call_quota.reset(token)
        caller = _caller_id(_caller_key())
        with _intro_lock:
            first_call = quota is not None and caller not in _intro_shown_for
            if first_call:
                _intro_shown_for.add(caller)
        note = _quota_note(quota, first_call)
        return f"{result}\n\n{note}" if note else result
    return wrapper


# --- Remote (HTTP) mode (Part D, 2026-09-26) -------------------------------------------------
# Locally the connector runs on the user's computer over stdio with the key from its own
# environment. Remote, one server answers many callers: each tool call uses the key sent in THAT
# request's header, so every question counts against the caller's own quota (quota attribution),
# and the server holds no key of its own. Same code, same tools; the transport is a startup flag.
_REMOTE = False
_call_status: contextvars.ContextVar = contextvars.ContextVar("baseline_call_status", default=None)
log = logging.getLogger("baseline_mcp")


def _key_from_headers(headers) -> str:
    """The caller's key from X-Api-Key or Authorization: Bearer. Never from the URL."""
    key = (headers.get("x-api-key") or "").strip()
    if not key:
        auth = (headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
    return key


def _caller_key() -> str:
    if not _REMOTE:
        return BASELINE_API_KEY
    from mcp.server.lowlevel.server import request_ctx
    try:
        request = request_ctx.get().request
    except LookupError:
        return ""
    return _key_from_headers(request.headers) if request is not None else ""


def _caller_id(key: str) -> str:
    """How logs name a caller: the start of the key's SHA-256, as the key registry does. Never
    the key itself."""
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()[:10] if key else "none"


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    key = _caller_key()
    if key:
        headers["X-Api-Key"] = key
    return headers


def _logged(tool):
    """Run a tool in a worker thread (a sync tool on the event loop would block every other
    caller for the length of a question) and log one line per call: tool, milliseconds, status,
    caller fingerprint. Never the key, never the arguments."""
    import anyio

    def _run(*args, **kwargs):
        token = _call_status.set("ok")
        try:
            return tool(*args, **kwargs), _call_status.get()
        finally:
            _call_status.reset(token)

    @functools.wraps(tool)
    async def wrapper(*args, **kwargs):
        start = time.monotonic()
        status, result = "exception", None
        try:
            result, status = await anyio.to_thread.run_sync(functools.partial(_run, *args, **kwargs))
            return result
        finally:
            log.info(json.dumps({"event": "tool", "tool": tool.__name__,
                                 "ms": round((time.monotonic() - start) * 1000),
                                 "status": status, "caller": _caller_id(_caller_key())}))
    return wrapper


_SCRUB = (
    (re.compile(r"(apikey|api_key|key|token)=[^&\s'\"]+", re.I), r"\1=[redacted]"),
    (re.compile(r"https?://[^\s'\"<>)]+"), "[address]"),
    (re.compile(r"(?<![\w.])/(?:opt|root|home|Users|mnt|var|tmp|private)/[^\s'\"]+"), "[path]"),
)


def _scrub(text: str) -> str:
    """No key, address or file path in anything relayed to a caller (P1-32). The caller's own key
    is removed too, in case an upstream message ever echoed it."""
    out = str(text)
    own = _caller_key() if _REMOTE else BASELINE_API_KEY
    if own and len(own) >= 8:
        out = out.replace(own, "[redacted]")
    for pattern, repl in _SCRUB:
        out = pattern.sub(repl, out)
    return out


def _post(path: str, payload: dict, timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict:
    """POST to a Baseline API path. Raises RuntimeError with an actionable
    message on any failure — callers should catch this and hand it back to the
    agent as the tool result, not let it surface as a stack trace."""
    url = f"{BASELINE_API_URL}{path}"
    try:
        response = httpx.post(url, json=payload, headers=_headers(), timeout=timeout)
    except httpx.ConnectError as error:
        _call_status.set("unreachable")
        # Hosted, the API is an internal address (http://127.0.0.1:5050) no caller should see, and
        # the exception text adds nothing a caller can act on (P1-32, 2026-09-29). Locally (stdio)
        # the URL is the user's own setting and helps them fix it.
        log.warning(json.dumps({"event": "api_unreachable", "detail": str(error)[:300]}))
        if _REMOTE:
            raise RuntimeError("Baseline's service couldn't be reached just now. Try again shortly.")
        raise RuntimeError(f"Could not reach the Baseline API at {url}. Is the server running?")
    except httpx.TimeoutException:
        _call_status.set("timeout")
        if _REMOTE:
            raise RuntimeError(f"Baseline took longer than {timeout:.0f}s to answer. Try again shortly.")
        raise RuntimeError(f"Baseline API at {url} timed out after {timeout:.0f}s.")

    if response.status_code >= 400:
        _call_status.set(f"http_{response.status_code}")
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
        # The API's own messages are written for users (its 5xx ones are fixed text since P1-32);
        # an HTML error page or anything else unexpected is not passed on.
        if not isinstance(detail, str) or detail.lstrip().startswith("<") or len(detail) > 1200:
            log.warning(json.dumps({"event": "api_error_body", "status": response.status_code,
                                    "detail": str(detail)[:300]}))
            detail = "Baseline couldn't answer this just now. Try again shortly."
        raise RuntimeError(f"Baseline API returned {response.status_code}: {_scrub(detail)}")

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

    lines.append(f"\n{_context_provenance_line(data)}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
@_logged
@_with_quota_note
def get_climate_context(query: str) -> str:
    """Past, recent and coming weather at a named place, measured against that
    place's own record since 1991. Use it for how wet, dry, hot or cold a place
    has been (this water year, last winter, a named month such as August 2026);
    whether that, or the next 10 days, is unusual; where a period ranks in the
    record ("2nd driest since 1991"); and how it compares with the 1991-2020
    normal. Answers are computed from ERA5-Land reanalysis (daily, about 10 km,
    land only) and Open-Meteo forecasts, not from news or web pages, and they
    state their own coverage.

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
@_logged
@_with_quota_note
def get_context_for_coordinates(latitude: float, longitude: float, label: str = "") -> str:
    """The next 10 days at an exact latitude and longitude (a field, property,
    trailhead or site), each day ranked against the same calendar day in every
    year since 1991 ("warmest October 5 since 1991"), plus where the water year
    stands there. Takes coordinates only, not a question, and skips place-name
    lookup. Land only. For a past period at a point, ask get_climate_context
    with the coordinates in the question.

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
@_logged
@_with_quota_note
def get_water_year_status(location: str) -> str:
    """How wet or dry, and warm or cold, a place has been so far this water year
    (from October 1 in North America; from January 1 elsewhere): totals,
    percent of normal, and the year's rank against the same span of every year
    since 1991 ("2nd driest since 1991"). The record publishes about a month
    behind, so in October it answers the water year just ended and says so.
    For drought, water supply, range, crop and fire questions. location can be
    a place name ("Casper WY") or "lat,lon" coordinates.

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
@_logged
@_with_quota_note
def compare_to_normal(location: str, variable: str, time_window: str = "") -> str:
    """Is the coming week unusually warm, cold, wet or dry? Ranks the forecast
    for the next few days (up to 10) at a place against the same days in every
    year since 1991, as percentiles and departures from normal. Forecast only:
    past weather ("last month", "this water year") is a question for
    get_climate_context, and windows beyond 10 days are declined.
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


_NO_DATA_GENERIC = "there's no data for this place and period"


def _format_compare_result(data: dict) -> str:
    comparison = data.get("comparison", {})
    lines = []
    if comparison.get("period_note"):
        # Said first: why this period. "Water Year 2027 began October 1 and there isn't enough data
        # yet; here's Water Year 2026, which just ended." (P1-49, 2026-10-01)
        lines += [comparison["period_note"], ""]
    lines += [
        f"Compared {comparison.get('n_locations')} locations — "
        f"{comparison.get('variable_label')}, {comparison.get('period_label')} "
        f"(vs. {comparison.get('baseline_years')} baseline)",
        "",
    ]

    for entry in comparison.get("ranked", []):
        label = entry.get("label", "Unknown")
        if entry.get("status") not in ("ok", "partial"):
            # Words, never the internal code (owner, 2026-10-01): the API sends reason_text; an
            # older API that doesn't gets the generic sentence, not "requested_period_extends_...".
            lines.append(f"- {label}: no data ({entry.get('reason_text') or _NO_DATA_GENERIC})")
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
        #
        # Ties share a position and say so (P1-15); no position at all when the
        # server withheld the group ranking (records ending on different dates).
        tied_with = entry.get("tied_with") or []
        position = "-" if rank is None else f"{rank}=" if tied_with else f"{rank}."
        tie = f", tied with {', '.join(tied_with)}" if tied_with else ""
        if entry.get("percent_of_normal") is not None:
            versus = f" ({entry['percent_of_normal']}% of normal{tie})"
        elif entry.get("departure_display") is not None:
            versus = f" ({entry['departure_display']} vs. normal{tie})"
        else:
            # A value with nothing measured against past years (partial period, or a
            # suppressed percent of normal): no "(None vs. normal)".
            versus = f" ({tie[2:]})" if tie else ""
        lines.append(f"{position} {label}: {value}{versus}")
        if rank_label:
            note = entry.get("rank_cluster_note")
            lines.append(f"   Historically: {rank_label} on record here"
                         + (f" — though {note}" if note else ""))
        # The row's own caveats (2026-09-29): a far record cell, corrected rainfall. The same
        # sentences a single-place answer about this location carries.
        for row_note in entry.get("notes") or []:
            lines.append(f"   Note: {row_note}")

    if comparison.get("coverage_note"):
        # The partial-period sentence (P1-14): printed, not left in the JSON block.
        lines.append(f"\n{comparison['coverage_note']}")
    if comparison.get("confidence"):
        lines.append(f"\nConfidence: {comparison['confidence']}")
    lines.append(f"\n{comparison.get('provenance', _PROVENANCE_LINE)}")

    lines.append("\n```json")
    lines.append(json.dumps(data, indent=2, default=str))
    lines.append("```")

    return "\n".join(lines)


@mcp.tool()
@_logged
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
    """Compare a region or a set of places on rainfall, temperature or snowfall
    over the same past period (this water year, a season, a month, or a ski
    season): 2-10 places such as towns across several counties, the farms or
    properties in a portfolio (as "lat,lon"), or a named group of places. For
    each place: its total or average, how far it is from normal (percent of
    normal for rain and snow, degrees for temperature), where that period
    stands in its own record since 1991 ("near average", "3rd wettest"), and
    its rank against the others. Use it whenever a question is about more than
    one place, for example whether an event was local or regional, or which
    sites fared worst, instead of asking about each place separately: the
    ranking is computed by Baseline, not by your own arithmetic. A county or
    other area isn't a point: give a town in it, or coordinates.

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

    unplaced: list = []
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
            # Each worker runs in a copy of this call's context: a plain pool thread does not
            # inherit it, and remotely the caller's key lives there (_caller_key).
            futures = {
                executor.submit(contextvars.copy_context().run, _resolve_location, text): i
                for i, text in enumerate(locations)
            }
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    resolved[i] = future.result()
                except RuntimeError as error:
                    errors[i] = str(error)
        # One entry that can't be placed no longer sinks the rest (owner, 2026-10-01): "Goshen County,
        # WY" in a list of four failed the whole comparison. Compare what resolves, and say in words
        # which entry was left out and why.
        unplaced = [(locations[i], _plain_reason(errors[i])) for i in range(len(locations)) if errors[i]]
        placed = [r for r in resolved if r is not None]
        if len(placed) < 2:
            return _unplaced_lines(unplaced, len(locations), compared=False)
        payload["locations"] = placed

    try:
        data = _post("/api/compare", payload, timeout=COMPARE_TIMEOUT_SECONDS)
    except RuntimeError as error:
        return str(error)

    if data.get("status") == "error":
        return data.get("error", "Unknown error from Baseline API.")

    if unplaced:
        return _unplaced_lines(unplaced, len(locations), compared=True) + "\n\n" + _format_compare_result(data)
    return _format_compare_result(data)


def _plain_reason(error: str | None) -> str:
    """The lookup's own sentence without the transport prefix ("Baseline API returned 400: ")."""
    return re.sub(r"^Baseline API returned \d+:\s*", "", (error or "").strip()) or "it couldn't be found"


def _unplaced_lines(unplaced: list, total: int, compared: bool) -> str:
    head = (f"Left out of the comparison: {len(unplaced)} of the {total} places asked for couldn't be placed."
            if compared else
            f"No comparison: a comparison needs at least two places, and {len(unplaced)} of the {total} "
            "asked for couldn't be placed.")
    return "\n".join([head] + [f"- {text}: {reason}" for text, reason in unplaced])


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
@_logged
@_with_quota_note
def get_seasonal_outlook(
    location: str,
    variables: list[str] | None = None,
    season: str = "",
) -> str:
    """Odds that the coming three-month season at a place will be warmer or cooler,
    wetter or drier than normal: calibrated probabilities for below, near and above
    normal, from ECMWF's SEAS5 seasonal forecast, with how well the outlook has tested
    at that place and season. A season-ahead outlook, not a 10-day forecast and not a
    record of past weather.

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


@mcp.custom_route("/healthz", methods=["GET"])
async def _healthz(request):
    """Liveness only, no key needed; says nothing about the Baseline API behind it."""
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})


_KEY_CHECK_TTL_SECONDS = 300.0
_key_checks: dict = {}          # caller id -> (valid, checked_at)


async def _key_is_valid(key: str) -> bool | None:
    """Ask the Baseline API whether a key is live (/api/usage costs no question). True, False,
    or None when the API can't say. Cached briefly per key fingerprint, so a session's many
    requests make one check, and a deactivated key stops working within minutes."""
    caller = _caller_id(key)
    hit = _key_checks.get(caller)
    if hit and time.monotonic() - hit[1] < _KEY_CHECK_TTL_SECONDS:
        return hit[0]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BASELINE_API_URL}/api/usage", headers={"X-Api-Key": key})
    except httpx.HTTPError:
        return None
    if response.status_code in (401, 403):
        valid = False
    elif response.status_code < 400:
        valid = True
    else:
        return None
    _key_checks[caller] = (valid, time.monotonic())
    return valid


def _auth_gate(app):
    """ASGI gate in front of the MCP app in remote mode: a request with no key, or a key the
    Baseline API does not know, gets a plain 401 before any MCP handling. /healthz is open."""
    async def _reply(send, status: int, message: str):
        body = json.dumps({"error": message}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def gate(scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            return await app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        key = _key_from_headers(headers)
        if not key:
            log.info(json.dumps({"event": "auth", "status": "missing_key", "caller": "none"}))
            return await _reply(send, 401, "A Baseline API key is required in the X-Api-Key "
                                            "header (or Authorization: Bearer).")
        valid = await _key_is_valid(key)
        if valid is None:
            log.info(json.dumps({"event": "auth", "status": "api_unreachable",
                                 "caller": _caller_id(key)}))
            return await _reply(send, 503, "The Baseline API could not be reached to check the "
                                            "key. Try again shortly.")
        if not valid:
            log.info(json.dumps({"event": "auth", "status": "invalid_key", "caller": _caller_id(key)}))
            return await _reply(send, 401, "That Baseline API key is not valid.")
        return await _logged_request(app, scope, receive, send, headers, _caller_id(key))
    return gate


# P1-31 (2026-09-28): claude.ai's requests were getting HTTP 400s the server never explained -- the
# MCP SDK answers some requests (an unsupported MCP-Protocol-Version header, a malformed body) before
# any tool runs, so no tool log line exists for them. One line per request: the JSON-RPC method(s)
# and id(s), the protocol-version header, whether a session id was sent, the status, and for an
# error the SDK's own message. Never the params (they hold the user's question) or the key.
_BODY_PEEK = 64 * 1024


def _rpc_summary(body: bytes) -> tuple[list, list]:
    try:
        msg = json.loads(body.decode("utf-8", "replace")) if body else None
    except ValueError:
        return ["<unparseable>"], []
    msgs = msg if isinstance(msg, list) else [msg] if isinstance(msg, dict) else []
    methods = [m.get("method") or ("<response>" if "result" in m or "error" in m else "<none>")
               for m in msgs if isinstance(m, dict)]
    ids = [m.get("id") for m in msgs if isinstance(m, dict) and m.get("id") is not None]
    return methods, ids


def _error_message(body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        return str((data.get("error") or {}).get("message") or data.get("error") or "")[:240]
    except (ValueError, AttributeError):
        return body[:240].decode("utf-8", "replace")


async def _logged_request(app, scope, receive, send, headers, caller):
    t0 = time.monotonic()
    body_seen = bytearray()
    state = {"status": None, "err": bytearray()}

    async def peek_receive():
        message = await receive()
        if message.get("type") == "http.request" and len(body_seen) < _BODY_PEEK:
            body_seen.extend(message.get("body", b"")[: _BODY_PEEK - len(body_seen)])
        return message

    async def peek_send(message):
        if message.get("type") == "http.response.start":
            state["status"] = message.get("status")
        elif (message.get("type") == "http.response.body" and (state["status"] or 0) >= 400
              and len(state["err"]) < 1024):
            state["err"].extend(message.get("body", b"")[:1024])
        await send(message)

    try:
        return await app(scope, peek_receive, peek_send)
    finally:
        methods, ids = _rpc_summary(bytes(body_seen))
        line = {"event": "http", "http_method": scope.get("method"), "status": state["status"],
                "rpc": methods, "rpc_id": ids[:5], "pv": headers.get("mcp-protocol-version", ""),
                "sid": bool(headers.get("mcp-session-id")), "ua": headers.get("user-agent", "")[:80],
                "caller": caller, "ms": round((time.monotonic() - t0) * 1000)}
        if (state["status"] or 0) >= 400:
            line["error"] = _error_message(bytes(state["err"]))
        log.info(json.dumps(line))


def main():
    """stdio (default: the local connector, unchanged) or http (the hosted server, Part D)."""
    import argparse
    parser = argparse.ArgumentParser(prog="baseline-mcp")
    parser.add_argument("--transport", choices=("stdio", "http"),
                        default=os.environ.get("BASELINE_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("BASELINE_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BASELINE_MCP_PORT", "8765")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
        return

    global _REMOTE
    _REMOTE = True
    # One JSON object per line on stdout (journald). The mcp library installs its own "rich"
    # handler on the root logger, which wraps lines; this logger bypasses it.
    import sys
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if BASELINE_API_KEY:
        log.warning(json.dumps({"event": "startup", "note": "BASELINE_API_KEY is set but ignored "
                                "in http mode; every call uses its caller's key"}))
    from mcp.server.transport_security import TransportSecuritySettings
    public_hosts = [h.strip() for h in os.environ.get(
        "BASELINE_MCP_PUBLIC_HOSTS", "mcp.baselinecontext.com").split(",") if h.strip()]
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"] + public_hosts,
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
        + [f"https://{h}" for h in public_hosts] + ["https://claude.ai"],
    )
    # Stateless: no session survives in memory, so a restart or reboot costs callers nothing.
    mcp.settings.stateless_http = True
    import uvicorn
    uvicorn.run(_auth_gate(mcp.streamable_http_app()), host=args.host, port=args.port,
                log_level="warning", access_log=False,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
