# Methodology

Every number Baseline returns — a percentile rank, a "wetter than normal" label, a water year total — comes from a specific, fixed process described here. Nothing in Baseline's output is generated or estimated by a language model. This document exists so anyone using Baseline, or building on top of it, can check that claim rather than take it on faith.

## The data: ERA5-Land reanalysis

Baseline's historical numbers come from **ERA5-Land**, a reanalysis dataset produced by the European Centre for Medium-Range Weather Forecasts (ECMWF). Reanalysis is not a network of weather stations — it's a physically consistent, gridded reconstruction of the atmosphere built by combining decades of observations (stations, satellites, weather balloons, ships, aircraft) with a fixed numerical weather model, run once, over the whole historical period.

That matters for a specific reason: station records are uneven. Stations open, close, move, get new instruments, or simply don't exist in a lot of the world's more sparsely monitored places. Comparing "this week vs. 1995" at a single station can mean comparing against a different instrument, a different location, or a gap in the record. A reanalysis grid doesn't have that problem — every grid cell has a complete, consistently-produced record for the full period, computed the same way in 2026 as it was for 1996. That consistency, more than raw accuracy at any single point, is why Baseline uses it as its historical baseline.

**Coverage:** 1991–2025, 0.1° resolution (roughly 11 km at the equator), land areas only. ERA5-Land doesn't produce values for ocean grid cells, so locations resolve to the nearest valid land point — this occasionally matters for small islands or immediate coastlines.

## Climatology normals vs. historical ranking — two different periods, on purpose

Baseline uses two different windows of the ERA5-Land record, for two different jobs:

- **"Normal" (the expected value for a given place and date)** is computed over **1991–2020** — the 30-year period the World Meteorological Organization (WMO) designates as the current standard climatological normal. This is the same convention national weather services use, so a Baseline "normal" means the same thing a meteorologist means by it.
- **Historical ranking** ("3rd driest since 1991," "wetter than 91% of years") is computed over the **full 1991–2025 record** — all years currently available, not just the 30-year normals window. A 35-year ranking window gives a more meaningful answer to "how unusual is this" than a 30-year one would, and it lets the most recent years be ranked against history at all, which a fixed 1991–2020 window couldn't do.

In short: Baseline tells you what's *normal* using the WMO standard, and tells you how *unusual* something is using the fullest record available. Both numbers are labeled with their source period in Baseline's response provenance.

## How rank and percentile are computed

For a given location, date, and variable (precipitation or temperature), Baseline pulls the matching value for every year in the ranking window and compares the current value against that full set:

- **Rank** ("3rd driest," "7th wettest") counts how many years in the record had a more extreme value, plus one. If two other years were wetter than this one, this one ranks 3rd wettest.
- **Percentile** ("wetter than 83% of years") is the share of years in the record at or below the current value. It answers "where does this year fall in the distribution," independent of how many years are in the record.

Both numbers describe the same underlying comparison from two different angles — rank is easier to say in a sentence, percentile is easier to compare across locations with different record lengths.

## Water year vs. calendar year

Baseline frames cumulative precipitation context two ways, depending on the user's location:

- **Water year** (Oct 1 – Sep 30), used for North American users. This is the standard US hydrological accounting year — it starts in the fall so a full winter snowpack season falls inside a single year, rather than being split across two calendar years.
- **Calendar year** (Jan 1 – Dec 31), used everywhere else.

This is a real limitation worth being upfront about: the Oct 1 water year start is a US-specific convention, not a global hydrological standard — other countries define their own water years differently, or don't use the concept at all. Baseline currently applies the US convention to North American locations and calendar year everywhere else; the rankings themselves are valid globally, but the Oct 1 start date for North America is a convention choice, not a universal one.

## Forecast data

Baseline's forward-looking numbers (the next 10 days) come from a separate source — **Open-Meteo** — and are never blended with, or used to adjust, the historical ranking. Forecast and historical context are always computed and reported independently.

## Known limitations

- **Land-only, 0.1° grid.** No ocean cells; locations near coastlines or on small islands resolve to the nearest valid land grid point, which may be a few kilometers away.
- **Archive lag.** The most recent 1–2 months of ERA5-Land data can arrive with precipitation before temperature is finalized. When that gap occurs, Baseline falls back to Open-Meteo's historical archive for temperature and flags the response accordingly — it does not leave the gap unfilled or guess.
- **Reanalysis vs. a specific station.** ERA5-Land is a model-assimilated reconstruction, not a direct instrument reading. It's built to be highly accurate and, critically, *consistent* across the full record — but a nearby station could show a somewhat different number for any single day.
- **Oct 1 water year is a US convention**, applied to North American locations by default (see above).

## Provenance line

Every Baseline response ends with a line like:

```
Source: Baseline v0.1.0 | ERA5-Land reanalysis 1991-2025 (35-yr daily climatology,
WMO 1991-2020 normals), 0.1-degree resolution, land-only | Forecast: Open-Meteo
```

Read left to right: the Baseline version that produced this answer (methodology changes bump the version), the historical dataset and the two windows described above, the spatial resolution, and the separate forecast source. If you're relaying a Baseline answer to someone else, this line is the citation.

## About this document

Baseline is built by someone with a background in operational climate services, including work with NOAA. That background is why the reanalysis-vs-station distinction and the "normal" vs. "ranking" period split above are treated as first-class product decisions rather than implementation details — they're the same distinctions a working climate scientist has to get right. Baseline's audience isn't limited to any one field; this methodology holds the same whether the question comes from a ski resort operator, an insurance analyst, a journalist, or a rancher.
