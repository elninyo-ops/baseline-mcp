"""Routing test: which tool does a model pick when a generic weather tool and
the six Baseline tools (descriptions exactly as deployed) are both offered?

Usage: python run_routing.py <questions.json> <baseline_tools.json> <out.json>
Reads the API key from ~/.config/baseline/anthropic_tests.env; never prints it.
"""
import json
import pathlib
import sys
import time

import anthropic

MODELS = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"]
TRIALS = 3

WEATHER_TOOL = {
    "name": "get_weather_forecast",
    "description": (
        "Get the current weather and forecast for a location: temperature highs and "
        "lows, chance and amount of precipitation, wind, cloud cover and conditions, "
        "for today and up to the next 7 days."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City or place name"},
            "days": {"type": "integer", "description": "Number of forecast days (1-7)"},
        },
        "required": ["location"],
    },
}


def load_key():
    env = pathlib.Path.home() / ".config/baseline/anthropic_tests.env"
    for line in env.read_text().splitlines():
        if line.startswith("BASELINE_TEST_ANTHROPIC_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("key not found")


def main():
    questions = json.load(open(sys.argv[1]))["questions"]
    baseline = json.load(open(sys.argv[2]))
    tools = [WEATHER_TOOL] + [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in baseline
    ]
    client = anthropic.Anthropic(api_key=load_key())
    rows = []
    for q in questions:
        for model in MODELS:
            for trial in range(TRIALS):
                for attempt in range(4):
                    try:
                        msg = client.messages.create(
                            model=model,
                            max_tokens=1024,
                            tools=tools,
                            messages=[{"role": "user", "content": q["question"]}],
                        )
                        break
                    except anthropic.APIError as e:
                        err = type(e).__name__
                        time.sleep(5 * (attempt + 1))
                else:
                    rows.append({**q, "model": model, "trial": trial, "error": err})
                    continue
                calls = [b for b in msg.content if b.type == "tool_use"]
                rows.append({
                    **q,
                    "model": model,
                    "trial": trial,
                    "first_tool": calls[0].name if calls else "none",
                    "all_tools": [c.name for c in calls],
                    "inputs": [c.input for c in calls],
                    "text": " ".join(b.text for b in msg.content if b.type == "text")[:400],
                })
                print(q["id"], model, trial, rows[-1].get("first_tool"), flush=True)
    json.dump(rows, open(sys.argv[3], "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
