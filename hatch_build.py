"""Fail the build when the version in server.json disagrees with pyproject.toml.

WHY THIS IS A BUILD HOOK AND NOT A TEST. The version lives in three places -- the project
version and two fields in server.json, the MCP registry manifest -- and nothing about a
mismatch is visible. A release with a stale server.json builds cleanly, uploads cleanly,
and quietly points the registry at an older version. That happened across 0.1.5, 0.1.6 and
0.1.7, so anyone installing from the registry got a build without the relay instruction,
the wording work or the seasonal tool.

Writing it down was tried first. The note is in CONTRIBUTING.md and it did not stop the
next three releases. This repository has no CI and no test runner, so a test would be one
more thing nobody runs; the build is the one step nobody skips before publishing. Getting
it wrong now produces no artifact at all.

It is deliberately forgiving about ABSENCE and strict about DISAGREEMENT: a source tree
without server.json is not a broken release, but a server.json that contradicts the
version being built is.
"""
from __future__ import annotations

import json
import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class VersionConsistencyHook(BuildHookInterface):
    PLUGIN_NAME = "version-consistency"

    def initialize(self, version, build_data):
        manifest = os.path.join(self.root, "server.json")
        if not os.path.exists(manifest):
            return
        with open(manifest) as fh:
            doc = json.load(fh)

        expected = self.metadata.version
        found = {"server.json: version": doc.get("version")}
        for i, package in enumerate(doc.get("packages") or []):
            found[f"server.json: packages[{i}].version"] = package.get("version")

        wrong = {where: got for where, got in found.items() if got != expected}
        if wrong:
            lines = "\n".join(f"    {where} = {got!r}" for where, got in sorted(wrong.items()))
            raise ValueError(
                f"\n\nVersion mismatch. pyproject.toml is building {expected!r}, but:\n"
                f"{lines}\n\n"
                f"  server.json is the MCP registry manifest. Publishing with it stale points\n"
                f"  the registry at an older version, and nothing else in the build or the\n"
                f"  upload will tell you. Set every field above to {expected!r} and rebuild.\n"
                f"  See the release section of CONTRIBUTING.md.\n")
