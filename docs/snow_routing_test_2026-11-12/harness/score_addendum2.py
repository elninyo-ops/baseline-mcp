"""Score addendum 2 (everyday "who do" misfire checks) and total its cost.

Usage: python score_addendum2.py <results_addendum2.jsonl> <out_summary.json>
Pass mark (committed beforehand): under C, a Hoodoo tool first in at most 1 of 9 runs.
"""
import collections
import json
import sys

PRICES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00),
          "claude-haiku-5-5": (0.10, 0.50)}


def family(name):
    if name == "get_weather_forecast":
        return "weather"
    if name.startswith("hoodoo__"):
        return "hoodoo"
    return name


rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
summary = collections.OrderedDict()
cost = 0.0
for r in rows:
    pi, po = PRICES[r["model"]]
    cost += (r["usage"]["input_tokens"] * pi + r["usage"]["output_tokens"] * po) / 1e6
    e = summary.setdefault(r["id"], {"question": r["question"], "B": [], "C": []})
    e[r["version"]].append(r)

out = {}
print("| id | question | B first | B any hoodoo | C first | C any hoodoo | pass |")
print("|---|---|---|---|---|---|---|")
for qid, e in summary.items():
    cells = {}
    for v in "BC":
        runs = e[v]
        first = collections.Counter(family(r["first_tool"]) for r in runs)
        any_h = sum(any(family(t) == "hoodoo" for t in r["all_tools"]) for r in runs)
        cells[v] = {"n": len(runs), "first": dict(first), "any_hoodoo": any_h}
    passed = cells["C"]["first"].get("hoodoo", 0) <= 1
    out[qid] = {"question": e["question"], **cells, "pass": passed}
    fmt = lambda c: ", ".join(f"{k} {n}" for k, n in sorted(c["first"].items(), key=lambda kv: -kv[1]))
    print(f"| {qid} | {e['question']} | {fmt(cells['B'])} | {cells['B']['any_hoodoo']} | "
          f"{fmt(cells['C'])} | {cells['C']['any_hoodoo']} | {'PASS' if passed else 'FAIL'} |")

print("\nversion C runs that called a Hoodoo tool:")
for r in rows:
    if r["version"] == "C" and any(family(t) == "hoodoo" for t in r["all_tools"]):
        calls = " ; ".join(f"{n}{json.dumps(i, ensure_ascii=False)}" for n, i in zip(r["all_tools"], r["inputs"]))
        print(f"{r['id']} {r['model'].split('-')[1]} {r['trial']}: {calls}")
        if r["text"]:
            print(f"    text: {r['text'][:200]}")
json.dump(out, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
print(f"\ncalls {len(rows)}, cost ${cost:.2f}")
