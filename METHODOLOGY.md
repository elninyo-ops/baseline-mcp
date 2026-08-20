# Methodology

Every number Baseline returns — a percentile rank, a "wetter than normal" label, a water year total — comes from a specific, fixed process described here. Nothing in Baseline's output is generated or estimated by a language model. This document exists so anyone using Baseline, or building on top of it, can check that claim rather than take it on faith.

## Different bases for different questions, always labeled

Baseline answers most questions from **ERA5-Land reanalysis** — described below, and still the right basis for historical ranking. But as of this release, when a nearby weather station has an adequate record, Baseline can also report what that station observed for the same period, alongside the reanalysis figure. Two sources exist now, not one, so the operating rule is stated plainly: **every number is labeled with the basis that produced it, and a ranking is always computed within a single basis, never mixed across them.** The sections below explain what each basis is for and why that rule holds without exception.

## The primary data: ERA5-Land reanalysis

Baseline's historical numbers come from **ERA5-Land**, a reanalysis dataset produced by the European Centre for Medium-Range Weather Forecasts (ECMWF). Reanalysis is not a network of weather stations — it's a physically consistent, gridded reconstruction of the atmosphere built by combining decades of observations (stations, satellites, weather balloons, ships, aircraft) with a fixed numerical weather model, run once, over the whole historical period.

That matters for a specific reason: station records are uneven. Stations open, close, move, get new instruments, or simply don't exist in a lot of the world's more sparsely monitored places. Comparing "this week vs. 1995" at a single station can mean comparing against a different instrument, a different location, or a gap in the record. A reanalysis grid doesn't have that problem — every grid cell has a complete, consistently-produced record for the full period, computed the same way in 2026 as it was for 1996. That consistency, more than raw accuracy at any single point, is why Baseline uses ERA5-Land as its default historical baseline and for every ranking.

**Coverage:** 1991–2025, 0.1° resolution (roughly 11 km at the equator), land areas only. ERA5-Land doesn't produce values for ocean grid cells. Within the regions Baseline has generated tile data for, a location that lands on an ocean or otherwise invalid grid cell resolves to the nearest valid land cell in the same tile — this is how most coastlines and larger islands are handled. It does not search beyond the tile the location falls in: a location outside Baseline's generated tile coverage altogether (some small or remote islands, for instance) doesn't get snapped to a distant tile's land data. Baseline reports plainly that no historical baseline is available there rather than substitute a real, but geographically unrepresentative, answer.

## When a station observation is used instead — or alongside

Reanalysis's consistency is exactly what makes it the wrong tool for a few real questions:

- **Point accuracy.** A grid cell averages roughly 11 km of terrain; a station measures one spot. For a location where that difference matters — a specific address, a specific field — a nearby station reading is a materially different, more literal number.
- **Citability.** A station observation is what a specific instrument recorded on a specific day. For someone building a case a skeptic will scrutinize (an insurance claim, a legal filing, testimony), that's a fundamentally different kind of evidence than a modeled grid value, even when the two numbers agree.
- **Near-real-time and pre-1991 data.** ERA5-Land's own archive lags several weeks behind the present, and doesn't extend before 1991. Many station records run current to within a day or two, and some run back a century or more.

Baseline's current station source is **ACIS** (the NOAA Regional Climate Center's Applied Climate Information System), a free, unauthenticated web service drawing on GHCN-Daily, COOP, and related U.S. station networks. Station support is built behind a source-agnostic interface (not an ACIS-specific one) so it can be extended to other networks later without changing how the rest of Baseline uses it — see "Open questions" below.

**Selection is nearest-with-an-adequate-record, not just nearest.** A search around the query point expands outward (in fixed steps) until enough candidate stations are found, capped at a hard maximum distance beyond which Baseline declines rather than reach further. Among candidates, the first station whose record is complete enough over the relevant comparison window is used — a station that looks ideal by distance and date range alone but has real gaps in its data is skipped in favor of one that's slightly farther away but actually reliable. Two completeness thresholds apply, calibrated against real station records, not chosen in the abstract:

- A lower threshold qualifies a station to report a **raw observed value** for the period in question.
- A higher threshold, only reached by a more complete record, additionally qualifies the station's **own rank and percentile** — computed entirely from that station's own history, never blended with ERA5-Land's.

A station that clears only the first threshold still contributes a real, useful number — it just isn't asked to support a percentile its record can't back up. Both thresholds are configurable and get revisited as real usage provides more data than the original calibration pass could.

## Cross-source agreement — how confident should you be in a number

When both ERA5-Land and a qualifying nearby station have a value for the same question, Baseline reports both, together with the difference between them — not as a replacement for either number, but as a separate signal about how much confidence that number deserves. "3rd driest water year in 35, and a nearby station agrees within a few percentage points" is a stronger statement than either number alone, and a real disagreement between the two is reported with the same visibility as agreement — a spread worth noticing is exactly the case where burying it in fine print would defeat the point.

**This agreement check is deliberately separate from ranking.** A rank or percentile is always computed within one basis — reanalysis compared only to reanalysis, a station compared only to its own record. The two are never combined into a single statistic. Agreement is a comparison of two already-independent results after the fact, not an input to either one.

**Not every pairing of sources is equally independent, and Baseline says so.** A station observation and a reanalysis grid value are a genuinely independent check on each other — one is a direct instrument reading, the other a modeled reconstruction that assimilates observations but isn't a copy of any single one. That's not true of every pair of sources Baseline might use in the future: a reanalysis product and a satellite-derived product that itself blends in station data (a category CHIRPS, mentioned below, would fall into) share enough underlying inputs that agreement between them is a weaker signal, not a second independent confirmation. Baseline tracks this distinction explicitly per pair of sources, so that if a less-independent pairing is ever added, the response language says so rather than defaulting to the stronger "independent check" phrasing that only station-vs-reanalysis has actually earned.

**One further nuance, specific to temperature:** a station's daily mean temperature is conventionally the midpoint of that day's recorded high and low. ERA5-Land's daily mean is a continuous average across the day. Even a perfectly-sited, gap-free station will show some spread against reanalysis from this difference in definition alone — not just from being a different source. Baseline surfaces this as a known, structural note wherever a temperature agreement comparison is shown, rather than letting a spread from definition alone read as a data discrepancy.

## Climatology normals vs. historical ranking — two different periods, on purpose

Baseline uses two different windows of the historical record, for two different jobs — this applies to both ERA5-Land and, where used, station data:

- **"Normal" (the expected value for a given place and date)** is computed over **1991–2020** — the 30-year period the World Meteorological Organization (WMO) designates as the current standard climatological normal. This is the same convention national weather services use, so a Baseline "normal" means the same thing a meteorologist means by it. When a station is used for cross-source agreement, its own normal is computed over this same 1991–2020 window — that shared convention is what makes the two "percent of normal" figures comparable at all.
- **Historical ranking** ("3rd driest since 1991," "wetter than 91% of years") is computed over the **full 1991–2025 record** for ERA5-Land — all years currently available, not just the 30-year normals window. A station's own rank or percentile, where reported, legitimately uses that station's own fullest available complete record instead, which can run longer than 1991–2025 — a longer record is one of the real reasons to use a station in the first place. This doesn't violate the single-basis ranking rule: it's still one dataset's own history, just not required to match ERA5-Land's specific year range.

In short: Baseline tells you what's *normal* using the WMO standard on whichever basis it's using, and tells you how *unusual* something is using the fullest record available on that same basis. Every number is labeled with its source and window in Baseline's response provenance.

## How rank and percentile are computed

For a given location, date, and variable (precipitation or temperature), Baseline pulls the matching value for every year in the ranking window and compares the current value against that full set:

- **Rank** ("3rd driest," "7th wettest") counts how many years in the record had a more extreme value, plus one. If two other years were wetter than this one, this one ranks 3rd wettest.
- **Percentile** ("wetter than 83% of years") is the share of years in the record at or below the current value. It answers "where does this year fall in the distribution," independent of how many years are in the record.

Both numbers describe the same underlying comparison from two different angles — rank is easier to say in a sentence, percentile is easier to compare across locations with different record lengths. This computation is structurally guarded against ever mixing two data sources into one ranking distribution: the code raises rather than allowing it, not just by convention.

## Water year vs. calendar year

Baseline frames cumulative precipitation context two ways, depending on the user's location:

- **Water year** (Oct 1 – Sep 30), used for North American users. This is the standard US hydrological accounting year — it starts in the fall so a full winter snowpack season falls inside a single year, rather than being split across two calendar years.
- **Calendar year** (Jan 1 – Dec 31), used everywhere else.

This is a real limitation worth being upfront about: the Oct 1 water year start is a US-specific convention, not a global hydrological standard — other countries define their own water years differently, or don't use the concept at all. Baseline currently applies the US convention to North American locations and calendar year everywhere else; the rankings themselves are valid globally, but the Oct 1 start date for North America is a convention choice, not a universal one.

## Forecast data

Baseline's forward-looking numbers (the next 10 days) come from a separate source — **Open-Meteo** — and are never blended with, or used to adjust, the historical ranking. Forecast and historical context are always computed and reported independently.

## Precipitation vs. snowfall — not the same variable

When Baseline reports "precipitation," that number is always **liquid-equivalent precipitation** — rain, or the melted-water equivalent of any frozen precipitation — from the same ERA5-Land source described above. It is not a measurement of snow depth or snowfall amount.

**Snowfall is a separate, more limited variable**, sourced differently: it comes from Open-Meteo's own ERA5 archive at 0.25° resolution (roughly 25 km, coarser than the 0.1° grid used for precipitation and temperature), because ERA5-Land itself does not produce a usable snowfall field. Snowfall is currently only available for comparing named locations against each other (for example, ranking ski resorts by seasonal snowfall) — it is not available as an answer to a question about a specific location on a specific date.

**Practical effect:** asking Baseline something like "was there a lot of snow in [place] on [date]" will be answered using precipitation, not snowfall — and, if the question uses a snow-specific word, the response says so explicitly rather than silently substituting one variable for the other. If you need an actual snow-depth or snowfall-amount answer for a specific date, Baseline does not currently provide that; the location-comparison snowfall figures are the only real snowfall numbers it computes.

## Known limitations

- **Land-only, 0.1° grid (ERA5-Land).** No ocean cells; locations near coastlines or on larger islands resolve to the nearest valid land grid point within the same tile, which may be a few kilometers away. Locations outside Baseline's generated tile coverage entirely — including some small or remote islands — aren't snapped to a distant tile's data; Baseline reports no historical baseline available for those instead.
- **Archive lag (ERA5-Land).** The most recent 1–2 months of ERA5-Land data can arrive with precipitation before temperature is finalized. When that gap occurs, Baseline falls back to Open-Meteo's historical archive for temperature and flags the response accordingly — it does not leave the gap unfilled or guess.
- **Reanalysis vs. a specific station.** ERA5-Land is a model-assimilated reconstruction, not a direct instrument reading. It's built to be highly accurate and, critically, *consistent* across the full record — but a nearby station could show a somewhat different number for any single day, which is exactly what the cross-source agreement check above is for.
- **Station record quality beyond a date range.** ACIS reports the *bounds* of a station's record (its earliest and latest date), not internal gaps, station moves, or instrument changes within that range. Baseline computes its own completeness check from the actual daily data before trusting a station's number, and applies stricter completeness requirements before trusting that station's own rank or percentile — but a station move or instrument change *within* an otherwise complete-looking stretch of days is not something either ACIS's metadata or Baseline's completeness check can detect. This is a real, acknowledged gap, not one Baseline claims to close.
- **Oct 1 water year is a US convention**, applied to North American locations by default (see above).

## Open questions — recorded, not yet resolved

**GHCNd and non-US commercial use.** GHCNd (the Global Historical Climatology Network – Daily) is the natural next station source beyond ACIS — over 100,000 stations across roughly 180 countries, with some records running back 175 years, versus ACIS's largely US-network coverage. It is not built into Baseline today. NOAA/NCEI's published GHCNd documentation states that non-US data, and products derived from it, are for non-commercial use and can't be redistributed or used to re-export a commercial service. Baseline is a commercial API. If that restriction holds as written, a GHCNd integration would need to be scoped to US stations only — which would make its real incremental value largely "the same US coverage ACIS already provides, plus non-US stations still off-limits for commercial use." This needs confirming directly with NCEI before any global GHCNd integration is designed around, and is recorded here specifically so it isn't discovered late, mid-build.

## Provenance line

Every Baseline response ends with a line like:

```
Source: Baseline v0.1.0 | ERA5-Land reanalysis 1991-2025 (35-yr daily climatology,
WMO 1991-2020 normals), 0.1-degree resolution, land-only | Forecast: Open-Meteo
```

When a station cross-check was used, the response's agreement data names the station, its distance, and whether its record was complete enough to support its own rank — that's the citation for the station-sourced half of the comparison, alongside this line for the reanalysis half.

Read left to right: the Baseline version that produced this answer (methodology changes bump the version), the historical dataset and the two windows described above, the spatial resolution, and the separate forecast source. If you're relaying a Baseline answer to someone else, this line is the citation.

## About this document

Baseline is built by someone with a background in operational climate services, including work with NOAA. That background is why the reanalysis-vs-station distinction, the "normal" vs. "ranking" period split, and the independence distinction between source pairings above are treated as first-class product decisions rather than implementation details — they're the same distinctions a working climate scientist has to get right. Baseline's audience isn't limited to any one field; this methodology holds the same whether the question comes from a ski resort operator, an insurance analyst, a journalist, or a rancher.
