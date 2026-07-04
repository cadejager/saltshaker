# tests/test_solve_optimized.py
from tests._support import mkfam
from saltshaker.clingo_solver import solve_optimized
from saltshaker.constraints import validate
from saltshaker.metrics import measure


def _canon(schedule):
    return [sorted((h.email, tuple(sorted(a.email for a in att))) for h, att in night.items())
            for night in schedule]


def test_feeds_everyone_valid_and_reconstructs():
    host = mkfam("h@x", space=8, host=[True])
    g1, g2 = mkfam("g1@x"), mkfam("g2@x")
    fams = [host, g1, g2]
    sched = solve_optimized(fams, seed=0, time_limit=5)
    assert validate(fams, sched) == []
    assert measure(fams, sched).unfed_count == 0
    assert sched[0][host] == {host, g1, g2}


def test_cap_holds():
    # two flexible hosts, few guests -> the cap forbids leaving > (maxspace-1) empty seats
    h1 = mkfam("h1@x", space=8, host=[True])
    h2 = mkfam("h2@x", space=8, host=[True])
    g1, g2, g3 = mkfam("g1@x"), mkfam("g2@x"), mkfam("g3@x")
    fams = [h1, h2, g1, g2, g3]
    sched = solve_optimized(fams, seed=0, time_limit=5)
    cap = 7  # max space 8 - 1
    for night in sched:
        empty = sum(host.space - sum(a.size for a in att) for host, att in night.items())
        assert empty <= cap


def test_reproducible_under_seed():
    fams = [mkfam("h@x", space=8, host=[True]), mkfam("g1@x"), mkfam("g2@x")]
    assert _canon(solve_optimized(fams, seed=3, time_limit=5)) == \
           _canon(solve_optimized(fams, seed=3, time_limit=5))


def test_lp_dump_written(tmp_path):
    lp = tmp_path / "obj.lp"
    solve_optimized([mkfam("h@x", space=8, host=[True]), mkfam("g@x")],
                    seed=0, time_limit=5, lp_path=str(lp))
    text = lp.read_text()
    assert "cap(7)." in text
    assert ":~ meet(A,B). [-1@2, A, B]" in text   # mixing rule dumped for audit
