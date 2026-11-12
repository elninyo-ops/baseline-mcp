"""Score the hoodoo trigger test against the pass criteria committed beforehand.

Usage: python score_hoodoo.py <results_raw.json> <out_summary.json>
Prints one markdown table per group and writes the counts to a summary file.
"""
import collections
import json
import sys

WEATHER = "get_weather_forecast"


def family(name):
    if name == WEATHER:
        return "weather"
    if name.startswith(("baseline__", "hoodoo__")):
        return "hoodoo"
    return name  # "none" or an error


def short(name):
    return name.split("__", 1)[-1] if "__" in name else name


rows = json.load(open(sys.argv[1]))
qs = collections.OrderedDict()
for r in rows:
    qs.setdefault(r["id"], {"question": r["question"], "group": r["group"], "runs": collections.defaultdict(list)})
    qs[r["id"]]["runs"][r["version"]].append(r)

summary = {}
for qid, q in qs.items():
    entry = {"question": q["question"], "group": q["group"]}
    for v in "ABC":
        runs = q["runs"][v]
        first_family = collections.Counter(family(r.get("first_tool", "error")) for r in runs)
        first_tool = collections.Counter(short(r.get("first_tool", "error")) for r in runs)
        any_hoodoo = sum(any(family(t) == "hoodoo" for t in r.get("all_tools", [])) for r in runs)
        by_model = {}
        for r in runs:
            by_model.setdefault(r["model"].split("-")[1], []).append(short(r.get("first_tool", "error")))
        entry[v] = {"n": len(runs), "first_family": dict(first_family), "first_tool": dict(first_tool),
                    "any_hoodoo_call": any_hoodoo, "by_model": by_model}
    c = entry["C"]
    c_errors = c["first_family"].get("error", 0)
    entry["C_runs_completed"] = c["n"] - c_errors
    if q["group"] == "trigger" and c["first_family"].get("hoodoo", 0) >= 8:
        entry["pass"] = True  # meets the mark whatever the missing runs would have done
    elif c_errors and q["group"] != "dictation":
        entry["pass"] = "incomplete"
    elif q["group"] == "trigger":
        entry["pass"] = c["first_family"].get("hoodoo", 0) >= 8
    elif q["group"] == "misfire":
        entry["pass"] = c["any_hoodoo_call"] <= 1
    elif q["group"] == "forecast":
        entry["pass"] = c["first_family"].get("weather", 0) >= 8
    else:
        entry["pass"] = None
    summary[qid] = entry

json.dump(summary, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)


def cell(e):
    ff = e["first_family"]
    parts = [f"{k} {n}" for k, n in sorted(ff.items(), key=lambda kv: -kv[1])]
    return ", ".join(parts) + (f" (any hoodoo: {e['any_hoodoo_call']})" if e["any_hoodoo_call"] and ff.get("hoodoo", 0) != e["any_hoodoo_call"] else "")


for group in ["trigger", "dictation", "misfire", "forecast"]:
    print(f"\n### {group}\n| id | question | A | B | C | pass |\n|---|---|---|---|---|---|")
    for qid, e in summary.items():
        if e["group"] != group:
            continue
        p = {True: "PASS", False: "FAIL", None: "n/a", "incomplete": "not run"}[e["pass"]]
        print(f"| {qid} | {e['question']} | {cell(e['A'])} | {cell(e['B'])} | {cell(e['C'])} | {p} |")

print("\n### which hoodoo tool / by model under C")
for qid, e in summary.items():
    print(qid, e["C"]["first_tool"], e["C"]["by_model"])
errs = [r for r in rows if "error" in r]
print("errors:", len(errs))
