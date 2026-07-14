# baseline-mcp

MCP server exposing [Baseline](../baseline/baseline_claude_code_briefing.md) as agent tools. Thin translation layer only — no climate logic lives here; every tool call is an HTTP request to the Baseline API. See `baseline_mcp_server_plan.md` in the Baseline project for the full design.

## Local setup

The venv lives outside this directory (`~/.venvs/baseline-mcp`) rather than in `.venv/` here, because this project sits under iCloud-synced `~/Documents` — iCloud evicts/re-materializes files inside large venvs unpredictably, which causes intermittent `ModuleNotFoundError`s. Keep it that way.

```bash
python3 -m venv ~/.venvs/baseline-mcp
~/.venvs/baseline-mcp/bin/pip install -e .
cp .env.example .env   # fill in BASELINE_API_URL and a free_api-tier BASELINE_API_KEY
```

Run against a local Baseline instance (`python3 app.py` in `../baseline`), then:

```bash
~/.venvs/baseline-mcp/bin/mcp dev src/baseline_mcp/server.py
```

## Status

MCP Task 1 (scaffold + `get_climate_context`) complete. See `baseline_mcp_server_plan.md` for the remaining build order.
