# Release 11 (MCP): the Hoodoo Weather rename and the API's source lines (2026-11-03; re-swept 2026-11-10)

`release/2026-11-rename` against the live `a417f08`. The full review, with the comparison data, is in the API repo:
`docs/release_11_review.md` on its `release/2026-11-rename`, section "The MCP". The design is
`docs/release_11_rename_design.md` there.

## What changed, file by file

- **`src/baseline_mcp/server.py`:**
  - The server name is "Hoodoo Weather".
  - The six tool names are unchanged. Each description equals `tests/data/tested_descriptions.json`, byte for
    byte: the trigger-tested version D, which passed every scored question
    (branch `hoodoo-trigger-test-2026-11-03`, local, results `083d587`).
  - The assessment header reads "Hoodoo Weather's own assessment".
  - "Hoodoo" in the quota notes, the error and auth-gate messages, and the "Hoodoo API returned" prefix that
    `_plain_reason` strips.
  - **The connector's own source-line builders are removed:** `_PROVENANCE_LINE`, `_SEASONAL_PROVENANCE_LINE`,
    `_record_years_used`, `_context_provenance_line` and `_with_snowfall_source`. All three formatters print the
    API's `sources`. Without `sources`, they print the fallback line `FALLBACK_SOURCES_LINE`.
  - **Allowed hosts** default to both `mcp.baselinecontext.com` and `mcp.hoodoowx.com` (`DEFAULT_PUBLIC_HOSTS`,
    `_public_hosts`).
- **Docs and packaging:**
  - `README.md`, `METHODOLOGY.md`, `CONTRIBUTING.md`, `server.json` and the `pyproject.toml` homepage now say
    Hoodoo Weather and give the hoodoowx.com addresses.
  - The README's tool list gains `get_seasonal_outlook`.
  - `server.json`: checked 2 of 2 changed entries. They are its one `packages` entry, seen by the gate as one
    removed and one added. The only change is the two environment-variable descriptions, "Baseline API" →
    "Hoodoo API". The name, version, identifier and variable names are unchanged.
  - Kept: the repo, package, command, module and registry names, and the `BASELINE_*` variables (owner D9).
- **Tests:**
  - New: `test_release11_names.py`, `test_release11_sources.py`, `data/tested_descriptions.json`.
  - Updated to the new strings: quota notes, compare unplaced.
  - Removed: `test_context_provenance.py`, together with three cases of `test_snowfall_source_line.py`. They
    tested the removed builders; their criteria are pinned in the API's `tests/test_source_lines.py`.

## Result (2026-11-10, after the API's rebase on 10f part 1, `8a350a5`)

- **A "Still working" reply prints no source line** (owner, 2026-11-03): `_format_context_result`, test first
  (`3c98f67` failed, `c467c1a` passes).
- **Suite:** 57 passed (`PYTHONPATH=src`). At `a417f08` it was 50.
- **Comparison** (the API repo's `docs/release_11_mcp_sweep.json`, recorded from a fresh copy of the rebased
  release API): 195 calls, valid, 0 errors on either side.
  - Tier 1: 182, of which 15 are "Still working" replies that now print no source line, as decided.
  - Unchanged: 13. **Tier 3: 0. Nothing lost.**
  - 8 corrections: the old line named ERA5-Land for data the answer didn't use.
- **No MCP change for the API's item 4** (hidden fields agree with the visible answer): the MCP prints the API's
  JSON as it is.
- The 2026-11-03 result (tier 3: 14 "Still working" replies, for the owner) is in git history; it is decided.
