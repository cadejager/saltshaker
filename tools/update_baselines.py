#!/usr/bin/env python3
"""Regenerate tests/baselines/<input>.json by running the solver N times.

Run from the repo root:  python tools/update_baselines.py
Commit the resulting JSON so quality changes show up as reviewable diffs.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests._support import run_solver  # noqa: E402
from saltshaker.constraints import validate  # noqa: E402
from saltshaker.metrics import measure  # noqa: E402

INPUTS = ["a2_in.csv", "anonymised_in.csv", "example_in.csv"]
TRIALS = 5
TIME = 0
ROOT = pathlib.Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "in"
OUT = ROOT / "tests" / "baselines"


def _agg(values):
    return {"min": min(values), "max": max(values)}


def build(name):
    meals, unfed, meets, dinners = [], [], [], []
    for _ in range(TRIALS):
        families, schedule = run_solver(EX / name, time=TIME)
        assert validate(families, schedule) == [], "%s produced a violation" % name
        m = measure(families, schedule)
        meals.append(m.meals)
        unfed.append(m.unfed_count)
        meets.append(m.new_meetings)
        dinners.append(m.dinners)
    data = {"trials": TRIALS, "time": TIME,
            "meals": {**_agg(meals), "floor": int(min(meals) * 0.8)},
            "unfed_count": {**_agg(unfed), "ceiling": max(unfed) + max(2, max(unfed))},
            "new_meetings": _agg(meets),
            "dinners": _agg(dinners)}
    (OUT / name.replace(".csv", ".json")).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("wrote baseline for", name)


if __name__ == "__main__":
    for n in INPUTS:
        build(n)
