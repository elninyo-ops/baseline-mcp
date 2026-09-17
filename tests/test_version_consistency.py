"""The three version fields must agree. Runnable without building anything.

The enforcement that matters is the build hook in hatch_build.py -- this repository has no
CI, so a test is one more thing nobody runs, and a stale server.json is invisible without
one. This file exists so the check can be run deliberately, and so the rule is stated
somewhere a reader looks for rules rather than only inside a build plugin.

    python3 tests/test_version_consistency.py      # no pytest needed
    pytest tests/                                  # if you have it
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml has no top-level version"
    return match.group(1)


def _server_json_versions() -> dict:
    doc = json.loads((ROOT / "server.json").read_text())
    found = {"server.json: version": doc.get("version")}
    for i, package in enumerate(doc.get("packages") or []):
        found[f"server.json: packages[{i}].version"] = package.get("version")
    return found


def test_server_json_matches_pyproject():
    """server.json is the MCP REGISTRY manifest. Publishing with it stale points the
    registry at an older version, and neither the build nor the upload complains -- which
    is how 0.1.5, 0.1.6 and 0.1.7 all shipped against a server.json still reading 0.1.4."""
    expected = _pyproject_version()
    wrong = {w: g for w, g in _server_json_versions().items() if g != expected}
    assert not wrong, (
        f"pyproject.toml is {expected!r} but {wrong}. Set every field to {expected!r}.")


def test_the_build_hook_is_registered():
    """The test is the reminder; the hook is the enforcement. If the hook is ever dropped
    from pyproject.toml, this rule goes back to being a note, and notes did not hold."""
    text = (ROOT / "pyproject.toml").read_text()
    assert "[tool.hatch.build.hooks.custom]" in text
    assert 'path = "hatch_build.py"' in text
    assert (ROOT / "hatch_build.py").exists()


if __name__ == "__main__":
    test_server_json_matches_pyproject()
    test_the_build_hook_is_registered()
    print(f"ok — all version fields agree at {_pyproject_version()}")
