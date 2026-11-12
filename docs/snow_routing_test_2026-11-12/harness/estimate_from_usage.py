"""Estimate a run's cost from the per-call usage recorded in results_rerun.jsonl.

Usage: python estimate_from_usage.py <results_rerun.jsonl> <n_questions> <versions e.g. BC>
"""
import collections
import json
import sys

PRICES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00),
          "claude-haiku-5-5": (0.10, 0.50)}

rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
n_q, versions = int(sys.argv[2]), sys.argv[3]
per = collections.defaultdict(list)
for r in rows:
    pi, po = PRICES[r["model"]]
    per[(r["version"], r["model"])].append(
        (r["usage"]["input_tokens"] * pi + r["usage"]["output_tokens"] * po) / 1e6)
total = high = 0.0
for v in versions:
    for m in PRICES:
        costs = per[(v, m)]
        avg, mx = sum(costs) / len(costs), max(costs)
        total += avg * n_q * 3
        high += mx * n_q * 3
        print(f"{v} {m}: avg ${avg:.4f}/call, max ${mx:.4f}/call, from {len(costs)} calls")
print(f"{n_q * 3 * len(versions) * 3} calls: estimate ${total:.2f}, worst case (every call at the max seen) ${high:.2f}")
