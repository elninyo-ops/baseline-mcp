"""Release 11 (API repo docs/release_11_rename_design.md §1.3, §1.4, §3.2; owner decisions 2026-11-03).

The connector is "Hoodoo Weather"; the six tool names are unchanged; the descriptions are the trigger-tested
text byte for byte (tests/data/tested_descriptions.json, version D of the 2026-11-03 rerun); no string a
user or the model sees names the old product; mcp.hoodoowx.com is an allowed host beside the old name.
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import baseline_mcp.server as srv

HERE = Path(__file__).resolve().parent
TESTED = json.loads((HERE / "data" / "tested_descriptions.json").read_text())["tools"]
WORD = re.compile(r"\bBaseline\b")


def _tools() -> dict:
    return {t.name: t.description for t in asyncio.run(srv.mcp.list_tools())}


def test_server_name_is_hoodoo_weather():
    assert srv.mcp.name == "Hoodoo Weather"


def test_the_six_tool_names_are_unchanged():
    assert sorted(_tools()) == sorted(["get_climate_context", "get_context_for_coordinates",
                                       "get_water_year_status", "compare_to_normal", "compare_locations",
                                       "get_seasonal_outlook"])


def test_descriptions_are_the_tested_text_byte_for_byte():
    tools = _tools()
    for name, text in TESTED.items():
        assert tools[name] == text, name


def test_assessment_header_says_hoodoo_weather():
    lines = srv._assessment_lines({"assessment": {"headline": "x"}})
    assert lines[0] == "\nHoodoo Weather's own assessment — relay this, do not compose your own:"


def _docstrings(tree) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                    and isinstance(b[0].value.value, str):
                out.add(id(b[0].value))
    return out


def test_no_old_product_name_in_any_string_a_user_or_the_model_sees():
    """Tool docstrings ARE user-visible (they are the descriptions), so they are checked too; only the
    module's and helpers' docstrings are skipped, and those are covered by the description test above."""
    path = Path(srv.__file__)
    tree = ast.parse(path.read_text())
    tool_docs = {id(f.body[0].value) for f in ast.walk(tree)
                 if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name in TESTED}
    skip = _docstrings(tree) - tool_docs
    hits = [f"{n.lineno}: {n.value[:80]!r}" for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and WORD.search(n.value)]
    assert hits == []


def test_both_mcp_hostnames_are_allowed_by_default(monkeypatch):
    monkeypatch.delenv("BASELINE_MCP_PUBLIC_HOSTS", raising=False)
    assert srv._public_hosts() == ["mcp.baselinecontext.com", "mcp.hoodoowx.com"]


def test_quota_note_says_hoodoo():
    note = srv._quota_note({"limit": 100, "remaining": 0, "reset_at": "2026-11-11T00:00:00Z"}, False)
    assert note.startswith("Hoodoo quota:")


def test_plain_reason_strips_the_new_prefix():
    assert srv._plain_reason("Hoodoo API returned 400: That sounds like an area.") == "That sounds like an area."
