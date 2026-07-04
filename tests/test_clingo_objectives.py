# tests/test_clingo_objectives.py
import pytest

from schedule import read_csv
from saltshaker.clingo_solver import solve_optimized
from saltshaker.constraints import validate
from saltshaker.metrics import measure

# (name, new_meetings floor, dinners ceiling or None)
CASES = [("a2_in.csv", 210, None), ("anonymised_in.csv", 215, None), ("example_in.csv", 110, 34)]


@pytest.mark.parametrize("name,meet_floor,dinner_ceiling", CASES)
def test_objectives_beat_baseline(name, meet_floor, dinner_ceiling, examples_dir):
    families = read_csv(str(examples_dir / name), 8)
    cap = max(f.space for f in families if any(f.host_nights)) - 1
    sched = solve_optimized(families, seed=0, time_limit=8)

    assert validate(families, sched) == [], \
        "%s: %s" % (name, [v.message for v in validate(families, sched)])
    m = measure(families, sched)
    assert m.unfed_count == 0, "%s left families unfed" % name
    for night in sched:                                   # wasted-seats cap holds
        empty = sum(h.space - sum(a.size for a in att) for h, att in night.items())
        assert empty <= cap, "%s night empty=%d > cap=%d" % (name, empty, cap)
    assert m.new_meetings >= meet_floor, \
        "%s new_meetings %d < floor %d" % (name, m.new_meetings, meet_floor)
    if dinner_ceiling is not None:
        assert m.dinners <= dinner_ceiling, \
            "%s over-hosted: %d dinners > %d" % (name, m.dinners, dinner_ceiling)


def test_a2_host_balance_beats_old_solver(examples_dir):
    families = read_csv(str(examples_dir / "a2_in.csv"), 8)
    sched = solve_optimized(families, seed=0, time_limit=8)
    hb = measure(families, sched).host_balance
    assert hb is not None
    assert hb["max_deviation"] <= 0.15, "a2 balance %.4f > 0.15" % hb["max_deviation"]
