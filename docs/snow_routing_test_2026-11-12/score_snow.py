"""Score the snow routing test against ../snow_routing_test_2026-11-12.json (pre-registered).

Usage (from this directory): python3 score_snow.py
Reads results_snow_D.jsonl and results_snow_E.jsonl. Writes results_summary_snow.json and prints a table.
"""
import collections
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
PRICES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00),
          "claude-haiku-5-5": (0.10, 0.50)}
CLIMATE = "hoodoo__get_climate_context"
NO_SNOW = re.compile(r"(not|n't|no|cannot|unable|lack|doesn.t|isn.t)\W+(?:\w+\W+){0,8}?snow", re.I)

prereg = json.load(open(HERE.parent / "snow_routing_test_2026-11-12.json"))
rows = {v: [json.loads(l) for l in open(HERE / f"results_snow_{v}.jsonl") if l.strip()] for v in "DE"}


def short(name):
    return name.split("__", 1)[-1]


def tally(v, qid):
    rs = [r for r in rows[v] if r["id"] == qid]
    first = collections.Counter(r["first_tool"] for r in rs)
    by_model = {m: dict(collections.Counter(r["first_tool"] for r in rs if r["model"] == m)) for m in PRICES}
    wrong = [{"model": r["model"], "trial": r["trial"], "tools": r["all_tools"], "inputs": r["inputs"]}
             for r in rs if r["first_tool"] != CLIMATE and r["first_tool"].startswith("hoodoo__")]
    says_no_snow = sum(1 for r in rs if NO_SNOW.search(r.get("text") or ""))
    return {"n": len(rs), "first_tool": dict(first.most_common()), "by_model": by_model,
            "other_hoodoo_calls": wrong, "text_says_no_snow": says_no_snow}


summary = collections.OrderedDict()
for q in prereg["questions"]:
    qid, g = q["id"], q["group"]
    d, e = tally("D", qid), tally("E", qid)
    if d["n"] != 9 or e["n"] != 9:
        ok = "incomplete"
    elif g == "snow":
        ok = e["first_tool"].get(CLIMATE, 0) == 9
    else:
        top_d = max(d["first_tool"].values())
        tied = [t for t, n in d["first_tool"].items() if n == top_d]
        top_e = max(e["first_tool"].values())
        e_top = [t for t, n in e["first_tool"].items() if n == top_e]
        ok = any(t in tied for t in e_top) and max(e["first_tool"].get(t, 0) for t in tied) >= top_d - 1
        q = {**q, "live_tool": tied}
    summary[qid] = {**q, "D": d, "E": e, "pass": ok}

cost, tok = collections.defaultdict(float), collections.Counter()
for v in "DE":
    for r in rows[v]:
        pi, po = PRICES[r["model"]]
        tok[f"{v}_in"] += r["usage"]["input_tokens"]
        tok[f"{v}_out"] += r["usage"]["output_tokens"]
        cost[v] += (r["usage"]["input_tokens"] * pi + r["usage"]["output_tokens"] * po) / 1e6

overall = "PASS" if all(s["pass"] is True for s in summary.values()) else "FAIL"
snow_d_problem = sum(1 for s in summary.values() if s["group"] == "snow" and s["D"]["first_tool"].get(CLIMATE, 0) < 9)
out = {"overall_E": overall, "snow_questions_failing_under_D": snow_d_problem,
       "calls": {v: len(rows[v]) for v in "DE"}, "tokens": dict(tok),
       "cost_usd": {v: round(c, 4) for v, c in cost.items()}, "questions": summary}
json.dump(out, open(HERE / "results_summary_snow.json", "w"), indent=1, ensure_ascii=False)


def fmt(counts):
    return ", ".join(f"{short(t)} {n}" for t, n in counts.items())


print("| id | group | question | D (live) first tool | E (new) first tool | E pass |\n|---|---|---|---|---|---|")
for qid, s in summary.items():
    p = {True: "PASS", False: "FAIL", "incomplete": "INCOMPLETE"}[s["pass"]]
    print(f"| {qid} | {s['group']} | {s['question']} | {fmt(s['D']['first_tool'])} | {fmt(s['E']['first_tool'])} | {p} |")
print("\nreply text says no snow (report only):",
      {qid: (s["D"]["text_says_no_snow"], s["E"]["text_says_no_snow"]) for qid, s in summary.items()
       if s["D"]["text_says_no_snow"] or s["E"]["text_says_no_snow"]})
print(f"\ncalls {out['calls']}, cost D ${cost['D']:.2f}, E ${cost['E']:.2f}")
print("snow questions not 9/9 to get_climate_context under D:", snow_d_problem)
print("OVERALL (E)", overall)
