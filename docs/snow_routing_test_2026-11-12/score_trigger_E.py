"""Score the original trigger test under version E with the unchanged 2026-10-20 scorers, and compare with D.

Usage (from this directory): python3 score_trigger_E.py
score_D.py from hoodoo-trigger-test-2026-11-03, adapted only in paths and labels. The E rows go to
harness/score_hoodoo.py and harness/score_addendum2.py in the version C slot, so C's criteria are applied to E.
The comparison is with D's results (trigger_results_summary_D_2026-11-03.json, copied unchanged).
Writes results_summary_trigger_E.json.
"""
import collections
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PRICES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00),
          "claude-haiku-5-5": (0.10, 0.50)}

prereg = json.load(open(HERE / "trigger_questions_2026-11-03.json"))
rows = [json.loads(l) for l in open(HERE / "results_trigger_E.jsonl") if l.strip()]
assert all(r["version"] == "E" for r in rows)
as_c = [{**r, "version": "C"} for r in rows]
w_rows = [r for r in as_c if r["group"] == "everyday_misfire"]
o_rows = [r for r in as_c if r["group"] != "everyday_misfire"]

tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "o.json").write_text(json.dumps(o_rows, ensure_ascii=False))
(tmp / "w.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in w_rows))
for script, inp, out in (("score_hoodoo.py", "o.json", "o_sum.json"),
                         ("score_addendum2.py", "w.jsonl", "w_sum.json")):
    print(f"\n## {script} (E rows in the C column)")
    print(subprocess.run([sys.executable, "-I", str(HERE / "harness" / script), str(tmp / inp),
                          str(tmp / out)], capture_output=True, text=True, check=True).stdout)
o_sum = json.load(open(tmp / "o_sum.json"))
w_sum = json.load(open(tmp / "w_sum.json"))
d_sum = json.load(open(HERE / "trigger_results_summary_D_2026-11-03.json"))["questions"]

counts = collections.Counter(r["id"] for r in rows)
summary = collections.OrderedDict()
for q in prereg["questions"]:
    qid = q["id"]
    d = d_sum[qid]
    if q["group"] == "everyday_misfire":
        e = w_sum[qid]["C"]
        entry = {"question": q["question"], "group": q["group"], "n": e["n"],
                 "first_family": e["first"], "any_hoodoo_call": e["any_hoodoo"], "pass": w_sum[qid]["pass"]}
    else:
        e = o_sum[qid]["C"]
        entry = {"question": q["question"], "group": q["group"], "n": e["n"],
                 "first_family": e["first_family"], "first_tool": e["first_tool"],
                 "any_hoodoo_call": e["any_hoodoo_call"], "by_model": e["by_model"], "pass": o_sum[qid]["pass"]}
    entry["D"] = {"first_family": d["first_family"], "first_tool": d.get("first_tool"),
                  "any_hoodoo_call": d["any_hoodoo_call"], "pass": d["pass"]}
    if counts[qid] != 9:
        entry["pass"] = "incomplete"
    summary[qid] = entry

tok = collections.Counter()
cost = collections.defaultdict(float)
for r in rows:
    pi, po = PRICES[r["model"]]
    tok["input"] += r["usage"]["input_tokens"]
    tok["output"] += r["usage"]["output_tokens"]
    cost[r["model"]] += (r["usage"]["input_tokens"] * pi + r["usage"]["output_tokens"] * po) / 1e6
scored = [e["pass"] for e in summary.values() if e["group"] != "dictation"]
overall = "PASS" if all(p is True for p in scored) and len(rows) == 261 else "FAIL"
out = {"version": "E", "calls": len(rows), "tokens": dict(tok),
       "cost_usd": round(sum(cost.values()), 4), "cost_by_model": {m: round(c, 4) for m, c in cost.items()},
       "overall": overall, "questions": summary}
json.dump(out, open(HERE / "results_summary_trigger_E.json", "w"), indent=1, ensure_ascii=False)

print("\n## E vs D\n| id | group | criterion measure | E | D | E pass |\n|---|---|---|---|---|---|")
for qid, e in summary.items():
    g = e["group"]
    if g in ("trigger", "dictation"):
        m, ev, dv = "Hoodoo first", e["first_family"].get("hoodoo", 0), e["D"]["first_family"].get("hoodoo", 0)
    elif g == "misfire":
        m, ev, dv = "any Hoodoo call", e["any_hoodoo_call"], e["D"]["any_hoodoo_call"]
    elif g == "forecast":
        m, ev, dv = "weather first", e["first_family"].get("weather", 0), e["D"]["first_family"].get("weather", 0)
    else:
        m, ev, dv = "Hoodoo first", e["first_family"].get("hoodoo", 0), e["D"]["first_family"].get("hoodoo", 0)
    p = {True: "PASS", False: "FAIL", None: "n/a (report only)", "incomplete": "INCOMPLETE"}[e["pass"]]
    print(f"| {qid} | {g} | {m} | {ev}/9 | {dv}/9 | {p} |")
print("\nfirst Hoodoo tool by question (E):",
      {qid: e.get("first_tool") for qid, e in summary.items() if e["group"] == "trigger"})
print(f"\ncalls {len(rows)}, tokens {dict(tok)}, cost ${sum(cost.values()):.2f}",
      {m: round(c, 2) for m, c in cost.items()})
print("OVERALL", overall)
