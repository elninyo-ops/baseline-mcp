"""Run an addendum's questions under chosen versions, using the resumable rerun harness.

Usage: python run_addendum.py <addendum.json> <version_dir> <versions e.g. BC> <out.jsonl>
Same call, save-after-every-call, resume and stop-on-error behaviour as rerun_hoodoo.py.
"""
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

import anthropic

import rerun_hoodoo as rh
from run_routing import MODELS, TRIALS, load_key


def main():
    questions = json.load(open(sys.argv[1]))["questions"]
    vdir = pathlib.Path(sys.argv[2])
    versions = sys.argv[3]
    out = pathlib.Path(sys.argv[4])
    tools = {v: json.load(open(vdir / f"version_{v}.json"))["tools"] for v in versions}

    jobs = [(v, q, m, t) for q in questions for v in versions for m in MODELS for t in range(TRIALS)]
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add(rh.key(r["version"], r["id"], r["model"], r["trial"]))
    todo = [j for j in jobs if rh.key(j[0], j[1]["id"], j[2], j[3]) not in done]
    print(f"{len(jobs)} jobs, {len(done)} already done, {len(todo)} to run", flush=True)

    client = anthropic.Anthropic(api_key=load_key(), max_retries=0, timeout=120)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda j: rh.one(client, tools, out, j), todo))
    print("STOPPED EARLY" if rh.stop.is_set() else "FINISHED", flush=True)


if __name__ == "__main__":
    main()
