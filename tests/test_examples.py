# tests/test_examples.py
import json
import pathlib

import pytest

from tests._support import run_solver
from saltshaker.constraints import validate
from saltshaker.metrics import measure

INPUTS = ["a2_in.csv", "anonymised_in.csv", "example_in.csv"]
TRIALS = 5
BASELINES = pathlib.Path(__file__).parent / "baselines"


@pytest.mark.parametrize("name", INPUTS)
def test_example_invariants_and_quality(name, examples_dir):
    """One set of TRIALS runs per input: assert the hard invariants on EVERY
    trial, and aggregate quality against the committed baseline. (Combined into
    a single test so the solver runs 15x total, not 30x.)"""
    base = json.loads((BASELINES / name.replace(".csv", ".json")).read_text())
    meals, unfed = [], []
    for _ in range(TRIALS):
        families, schedule = run_solver(examples_dir / name, time=0)
        violations = validate(families, schedule)
        assert violations == [], "%s: %s" % (name, [v.message for v in violations])
        m = measure(families, schedule)
        meals.append(m.meals)
        unfed.append(m.unfed_count)
    assert min(meals) >= base["meals"]["floor"], \
        "%s meals %d below floor %d" % (name, min(meals), base["meals"]["floor"])
    assert max(unfed) <= base["unfed_count"]["ceiling"], \
        "%s unfed %d above ceiling %d" % (name, max(unfed), base["unfed_count"]["ceiling"])


def test_all_host_target_input_does_not_crash(examples_dir):
    # Regression for the ZeroDivisionError fixed in 3549778: every family in
    # anonymised_in.csv has a host_target, so there are zero flexible hosts.
    families, schedule = run_solver(examples_dir / "anonymised_in.csv", time=0)
    assert isinstance(schedule, list)
