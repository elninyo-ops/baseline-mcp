# Contributing

`baseline-mcp` is a thin translation layer. **No climate logic lives here** — every tool call is
an HTTP request to the Baseline Climate API, and rankings, station cross-checks and outlook
calibration all happen server-side. A change to what an answer *says* almost always belongs in the
API, not in this package.

## Local development

**Keep the venv outside this directory.** This project sits under iCloud-synced `~/Documents`, and
iCloud evicts and re-materialises files inside large venvs unpredictably, which shows up as
intermittent `ModuleNotFoundError`. A `.venv/` here will appear to work and then fail on a later
run for no visible reason.

```bash
python3 -m venv ~/.venvs/baseline-mcp
~/.venvs/baseline-mcp/bin/pip install -e .
```

## Running against the MCP Inspector

```bash
~/.venvs/baseline-mcp/bin/mcp run src/baseline_mcp/server.py
```

**Not `uv run`.** It auto-creates a local `.venv/` and `uv.lock` inside the iCloud-synced
directory on every reconnect. `uv*.lock` is gitignored, but the Inspector's connection panel still
defaults to `uv run` on a fresh connect — repoint the Command field by hand each time.

## Releasing

```bash
rm -rf dist/ build/       # a stale dist/ will re-upload the PREVIOUS version and be rejected
python -m build           # or: uv build
twine check dist/*        # confirm the version you expect, and only that version
twine upload dist/*       # or: uv publish
```

The index can lag a minute or two behind a successful upload, so a check immediately after
publishing may still show the previous version. Verify against
`https://pypi.org/simple/baseline-mcp/` rather than assuming either way.
