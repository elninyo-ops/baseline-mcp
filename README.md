# Baseline Climate

<!-- mcp-name: io.github.elninyo-ops/baseline-mcp -->

**Stop your agent inventing climate context.** Ranked 35-year records for any point on Earth,
cross-checked against real stations, with an explicit reliability note to relay instead of guess.

---

Ask it something, and this is what comes back.

*A ranking — with the near-tie disclosed, and a station agreeing:*

> **August 2026:** Mean temperature was 75°F, +2.8°F from normal, ranking as the **8th warmest
> since 1991** — though the 7th warmest through 9th warmest years are within 0.7°F of each other.
> A nearby station (CASPER-NATRONA COUNTY AP, 8.4 mi) **agrees**: +2.1°F from its own normal,
> against the reanalysis's +2.8°F.

*A station that does **not** agree — the gauge a mile away read half the grid's total:*

> **March 2026:** Precipitation totaled 2.30 in — near average for this period historically.
> A nearby station (BOZEMAN MONTANA STATE UNIVERSITY, 1.3 mi) **measured 1.12 in, against the
> reanalysis's 2.30 in.**

*A wind ranking that says plainly it is modeled, not measured:*

> **March 2026:** Modeled peak gust: 60 mph, ranking as the **3rd gustiest since 1991** — though
> it's within 1 mph of the 6th gustiest year. A station (Saratoga, 32.1 mi) measured a peak gust
> of 59 mph. The reanalysis figure is **a modeled estimate, not a direct reading**.

*A seasonal outlook carrying its own skill label:*

> **Leaning wetter than normal for Sep–Nov in Nairobi, on odds we haven't been able to verify
> here** — below normal 5%, near normal 19%, above normal 76%. Forecasts here do track wetter and
> drier seasons, so the direction is the part worth using; whether the percentages themselves beat
> a climatological guess **has not been shown**.

Four things worth noticing. It gives you the rank, not just the number. It tells you when the rank
is a near-tie, so you don't over-read it. It goes and asks a real weather station whether the
gridded record is right — and when the station disagrees, **it says so** rather than papering
over it. And when it can't vouch for its own forecast, it tells you that too.

## The data isn't new. Asking it a question is.

ERA5 has been sitting in public archives for years. Interrogating it meant knowing which dataset,
writing the code, and having an afternoon. That cost is what collapsed — and the interesting
consequence is that people now ask things they'd never have thought worth the trouble.

The Bozeman example above isn't a weather lookup. It's a construction schedule dispute, where the
question was whether rain actually stopped work — and the gridded record said one thing while the
gauge a mile away said another. The wind example is a trucking corridor. Neither would have been
worth opening a climate dataset for. Both take a sentence now.

That's the claim: not that historical weather data exists, but that the cost of asking it a real
question has fallen far enough that weather becomes one ordinary input into questions that aren't
about weather.

## What it won't claim

Most tools hand you a number. This one hands you the number **and its standing**.

- **Near-ties are disclosed.** "8th warmest — though the 7th through 9th are within 0.7°F" stops a
  model reporting a rank as though it were a meaningful gap.
- **Station disagreement moves confidence**, and says which way. A gauge reading 1.12 in against a
  grid's 2.30 in is reported, not averaged away.
- **When no cross-check ran, it says why** — no nearby station, outside the covered region, source
  didn't respond. The gap is named rather than left for the model to fill.
- **Seasonal outlooks carry an honest skill label.** Calibrated from ECMWF SEAS5 against 35 years
  of observations, then labelled by what testing actually showed: that the odds beat a
  climatological guess here, or that only the direction is worth using, or — where a simple
  warming trend predicted the season better than the model did — that the model isn't the thing to
  go on. **We publish the cases where our own forecast isn't the best available answer.**

Every response carries an `assessment` field with Baseline Climate's own confidence statement, and
the tool descriptions instruct the model to relay it rather than compose its own. That exists
because the failure mode is real: given a bare number, models invent records that weren't broken,
assert a dataset is unreliable somewhere it isn't, and recycle one station disagreement across
unrelated answers.

## What it's made of

| | |
|---|---|
| Global daily record | **ERA5-Land reanalysis**, 0.1°, 1991–present, land-only |
| Station cross-check | **ACIS** (NOAA RCC). **United States only** — outside the US, answers say plainly that no station check ran |
| Seasonal outlook | **ECMWF SEAS5**, calibrated per region. **Precipitation only** — temperature has not yet cleared our skill test, and we don't issue one until it does |
| Forecast | Open-Meteo |

Rankings use the full 1991–present record; "normal" means the WMO 1991–2020 reference period. See
[METHODOLOGY.md](https://github.com/elninyo-ops/baseline-mcp/blob/main/METHODOLOGY.md) for how rankings, percentiles and water years are computed,
and where the limits are.

## Tools

- **`get_climate_context`** — a natural-language question; forecast plus 35-year ranked context.
- **`get_context_for_coordinates`** — the same for an exact lat/lon.
- **`get_water_year_status`** — precipitation and temperature since the start of the water year,
  ranked against 35 years.
- **`compare_to_normal`** — how unusual near-term conditions are at one location.
- **`compare_locations`** — rank precipitation, temperature or snowfall across 2–10 locations, or
  a curated category, over a water year, season, month or ski season.

## Install

Requires an API key. **Self-serve signup isn't available yet** — email Chad McNutt
(chadmcnutt@gmail.com) during this early period.

```bash
pip install baseline-mcp     # or: uvx baseline-mcp
```

**Claude Code**

```bash
claude mcp add baseline \
  --env BASELINE_API_URL=https://api.baselinecontext.com \
  --env BASELINE_API_KEY=your-key-here \
  -- uvx baseline-mcp
```

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "baseline": {
      "command": "uvx",
      "args": ["baseline-mcp"],
      "env": {
        "BASELINE_API_URL": "https://api.baselinecontext.com",
        "BASELINE_API_KEY": "your-key-here"
      }
    }
  }
}
```

**Cursor** — `.cursor/mcp.json`, same shape as above.

**As an HTTP server** (streamable HTTP, for hosting behind a reverse proxy):

```bash
BASELINE_API_URL=https://api.baselinecontext.com baseline-mcp --transport http --port 8765
```

It serves `/mcp` on 127.0.0.1 and holds no key of its own: every request must carry the caller's
key in an `X-Api-Key` (or `Authorization: Bearer`) header, and each tool call is made with that
key, so it counts against that key's own quota. A request without a valid key gets a 401. The
default, `--transport stdio`, is the local server shown above.

## Contributing

This package is a thin translation layer: no climate logic lives here, and every tool call is an
HTTP request to the Baseline Climate API. See `CONTRIBUTING.md` in [the repository](https://github.com/elninyo-ops/baseline-mcp) for local
development setup.

MIT licensed.
