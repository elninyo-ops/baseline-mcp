# baseline-mcp

<!-- mcp-name: io.github.elninyo-ops/baseline-mcp -->

MCP server exposing Baseline as agent tools — statistically rigorous weather and climate context, not just current conditions. Thin translation layer only: no climate logic lives here, every tool call is an HTTP request to the Baseline API. See `baseline_mcp_server_plan.md` in the Baseline project for the full design, and [`METHODOLOGY.md`](./METHODOLOGY.md) for how the underlying data and rankings are computed.

## Tools

- `get_climate_context` — natural-language weather and climate questions, full context back (forecast + 35-year historical percentile ranking).
- `get_context_for_coordinates` — same, for an exact lat/lon rather than a place name.
- `get_water_year_status` — precipitation/temperature status since the start of the water year (Oct 1 US / Jan 1 elsewhere), ranked against 35 years.
- `compare_to_normal` — how unusual current or forecast conditions are at one location.
- `compare_locations` — rank precipitation or temperature across 2-10 locations (or a curated category like `colorado_ski_resorts`) in a single call.

## Installation

Requires a Baseline API key. **Self-serve signup isn't available yet** — during this early period, contact Chad McNutt (chadmcnutt@gmail.com) for a key.

```bash
pip install baseline-mcp
# or: uvx baseline-mcp
```

Then add it to your MCP client's config, with your API key:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "baseline": {
      "command": "uvx",
      "args": ["baseline-mcp"],
      "env": {
        "BASELINE_API_URL": "https://api.baseline.example",
        "BASELINE_API_KEY": "your-key-here"
      }
    }
  }
}
```

**Claude Code**: `claude mcp add baseline --env BASELINE_API_URL=https://api.baseline.example --env BASELINE_API_KEY=your-key-here -- uvx baseline-mcp`

**Cursor** (`.cursor/mcp.json` or global MCP settings): same shape as the Claude Desktop config above, under whatever key Cursor's MCP settings use for server name.

## Local development

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

All 5 tools built and tested against a live local Baseline instance, including tool-selection validation in Claude Desktop. `METHODOLOGY.md` (trust collateral) complete. See `baseline_mcp_server_plan.md` in the Baseline project for full task history. **Published to [PyPI](https://pypi.org/project/baseline-mcp/) as of 0.1.0.**
