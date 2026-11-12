# Snow routing fix (MCP only): four tool descriptions (2026-11-12)

`fix/2026-11-snow-tool-descriptions`, from `8c174b1` (live, `release/2026-11-rename`). This changes no API and nothing in the API repo.

## What changed, file by file

- **`src/baseline_mcp/server.py`:** the docstrings of four tools changed, and nothing else did.
  - This was checked in code: with every docstring removed, the syntax tree is identical to 8c174b1's.
  - Tool names, arguments, schemas and behaviour are unchanged.
  - `get_climate_context`:
    - it answers snow questions (snow so far this season, the snow season to date, how snowy a past winter or ski season was);
    - it is the Hoodoo tool for any weather question asked in plain words;
    - "snowy" is added to "how wet, dry, hot or cold";
    - two new forms, "How much snow has LOCATION had so far this season?" and "How snowy was last winter in LOCATION?". The API's own tests pin both as the snow season (`tests/test_10f1_amendment2.py`, `test_10f1_amendment1.py` on the API's `release/2026-11-rename`).
  - `get_water_year_status`: it covers precipitation (rain, with any snow counted as melted water) and temperature only, not snowfall. Snow questions go to `get_climate_context`.
  - `compare_to_normal`: snow is not a variable here, so a snow question goes to `get_climate_context`.
  - `compare_locations`: a question about one place, snow included, goes to `get_climate_context`, and the model shouldn't add places to make a comparison.
  - `get_context_for_coordinates` and `get_seasonal_outlook` are unchanged.
- **`tests/data/tested_descriptions.json`:** now version E, the tested text, with the previous metadata kept under `previous`. `test_descriptions_are_the_tested_text_byte_for_byte` pins it.
- **`docs/snow_routing_test_2026-11-12.json`, `docs/snow_routing_test_2026-11-12/`:** the pre-registered routing test, its harness, results and `STATUS.md`. These are not deployed.

## Result

- The routing test is in `docs/snow_routing_test_2026-11-12/STATUS.md`.
  - 10 of 11 snow questions pass, 9 of 9 each. Live managed 0 of 11 at 9 of 9.
  - All 9 controls are unchanged.
  - S11, a snow forecast against normal, fails. No Hoodoo tool ranks forecast snow against normal.
  - The original trigger test passes under E.
- **Suite:** 57 passed (`PYTHONPATH=src`), the same count as 8c174b1.
- `server.json`, `pyproject.toml` and the version are unchanged. This deploy is a server-side description change only, with no PyPI or registry release.
