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

**The version lives in THREE places and all three must move together.**

| file | field |
|---|---|
| `pyproject.toml` | `version` |
| `server.json` | `version` (top level) |
| `server.json` | `packages[0].version` |

`pyproject.toml` is what PyPI publishes. **`server.json` is the MCP registry manifest**, and
nothing in the build will complain if it disagrees — a release with a stale `server.json`
publishes fine and quietly points the registry at an older version. That is not
hypothetical: `server.json` sat at `0.1.4` through the 0.1.5, 0.1.6 and 0.1.7 releases,
so anyone installing from the registry got a build without the relay instruction, the
wording work or the seasonal tool.

```bash
# 1. bump all three fields above, and check them:
grep -n '^version' pyproject.toml && grep -n '"version"' server.json

rm -rf dist/ build/       # a stale dist/ will re-upload the PREVIOUS version and be rejected
python -m build           # or: uv build
twine check dist/*        # confirm the version you expect, and only that version
twine upload dist/*       # or: uv publish
```

Worth confirming from the built artifact rather than the source tree, because a malformed
`pyproject.toml` can drop fields silently — a `[project.urls]` table placed above `keywords`
swallowed the keywords, classifiers and dependencies at 0.1.7 and still built:

```bash
python -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); \
  m=[n for n in z.namelist() if n.endswith('METADATA')][0]; print(z.read(m).decode()[:800])" \
  dist/*.whl
```

The index can lag a minute or two behind a successful upload, so a check immediately after
publishing may still show the previous version. Verify against
`https://pypi.org/simple/baseline-mcp/` rather than assuming either way.
