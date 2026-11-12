"""Hoodoo trigger test rerun: the version C calls that failed, plus the addendum questions.

Usage: python rerun_hoodoo.py <results_raw.json> <addendum.json> <version_dir> <out.jsonl>
Appends one JSON line per finished call and skips calls already in the file,
so it resumes after an interruption. Records token usage per call. Stops the
whole run, without retrying, on credit, rate-limit, auth or other 4xx errors;
only connection errors and 5xx are retried, twice.
"""
import json
import pathlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic

from run_routing import MODELS, TRIALS, load_key

stop = threading.Event()
lock = threading.Lock()


def key(v, qid, model, trial):
    return f"{v}|{qid}|{model}|{trial}"


def one(client, tools, out, job):
    v, q, model, trial = job
    if stop.is_set():
        return
    for attempt in range(3):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=1024,
                tools=tools[v],
                messages=[{"role": "user", "content": q["question"]}],
            )
            break
        except (anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(5 * (attempt + 1))
        except anthropic.APIStatusError as e:
            stop.set()
            print(f"STOP {v} {q['id']} {model} {trial}: {e.status_code} {e.message[:200]}", flush=True)
            return
    else:
        print(f"GAVE UP {v} {q['id']} {model} {trial}: connection/5xx", flush=True)
        return
    calls = [b for b in msg.content if b.type == "tool_use"]
    row = {
        **q,
        "version": v,
        "model": model,
        "trial": trial,
        "first_tool": calls[0].name if calls else "none",
        "all_tools": [c.name for c in calls],
        "inputs": [c.input for c in calls],
        "text": " ".join(b.text for b in msg.content if b.type == "text")[:600],
        "usage": {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens},
        "request_id": msg._request_id,
    }
    with lock:
        with open(out, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(v, q["id"], model, trial, row["first_tool"], flush=True)


def main():
    raw = json.load(open(sys.argv[1]))
    addendum = json.load(open(sys.argv[2]))["questions"]
    vdir = pathlib.Path(sys.argv[3])
    out = pathlib.Path(sys.argv[4])
    tools = {v: json.load(open(vdir / f"version_{v}.json"))["tools"] for v in "ABC"}

    qfields = ("id", "group", "question")
    jobs = [(r["version"], {k: r[k] for k in qfields}, r["model"], r["trial"])
            for r in raw if "error" in r]
    jobs += [(v, q, m, t) for q in addendum for v in "ABC" for m in MODELS for t in range(TRIALS)]

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add(key(r["version"], r["id"], r["model"], r["trial"]))
    todo = [j for j in jobs if key(j[0], j[1]["id"], j[2], j[3]) not in done]
    print(f"{len(jobs)} jobs, {len(done)} already done, {len(todo)} to run", flush=True)

    client = anthropic.Anthropic(api_key=load_key(), max_retries=0, timeout=120)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda j: one(client, tools, out, j), todo))
    print("STOPPED EARLY" if stop.is_set() else "FINISHED", flush=True)


if __name__ == "__main__":
    main()
