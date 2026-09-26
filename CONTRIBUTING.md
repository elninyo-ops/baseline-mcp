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

# 2. build
rm -rf dist/ build/       # a stale dist/ will re-upload the PREVIOUS version and be rejected
uv build

# 3. upload to PyPI with the conda twine (reads the token from ~/.pypirc)
TWINE=/opt/anaconda3/envs/baseline/bin/twine
$TWINE check dist/*       # confirm the version you expect, and only that version
$TWINE upload dist/*

# 4. the MCP registry: log in IMMEDIATELY before publishing (see below)
mcp-publisher login github
mcp-publisher publish
```

**Upload with the conda twine, not `uv publish`.** The PyPI token lives in `~/.pypirc`, and only
twine reads that file. `uv publish` ignores it and prompts for a username and password (0.1.9,
2026-09-26). There is no token in the environment, the keychain or a uv config, on purpose: one
copy, in `~/.pypirc`. `twine` is not on the PATH; use the full path above.

**The twine must be recent enough for the build's metadata.** Current `uv build` and
`python -m build` write core metadata 2.5, and the conda twine at 6.2.0 rejected it. It was
upgraded to 7.0.0 on 2026-09-26. If `twine check` complains about the metadata version, upgrade
it: `/opt/anaconda3/envs/baseline/bin/python -m pip install --upgrade twine`.

**Log in to `mcp-publisher` right before `mcp-publisher publish`, not earlier.** The GitHub login
expires, and one that died between the PyPI upload and the registry step failed with only "token
is expired". Logging in again and re-running `publish` is all it takes; the PyPI upload doesn't
need repeating.

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
