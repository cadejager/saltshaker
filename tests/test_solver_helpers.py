# tests/test_solver_helpers.py
from tests._support import mkfam
from saltshaker.balance import compute_cap
from saltshaker.clingo_solver import compute_target


def test_compute_target_zero_without_flexible_hosts():
    # only a targeted host -> no flexible hosts -> T = 0 (aux skipped)
    h = mkfam("h@x", space=8, host_target=1, host=[True])
    g = mkfam("g@x")
    fams = [h, g]
    assert compute_target(fams, compute_cap(fams), seed=0, time_limit=5) == 0


def test_compute_target_counts_flexible_host_slots():
    # one flexible host must host both nights to feed the guest -> T = 2
    h = mkfam("h@x", space=8, host=[True, True], attend=[True, True], nights=2)
    g = mkfam("g@x", host=[False, False], attend=[True, True], nights=2)
    fams = [h, g]
    assert compute_target(fams, compute_cap(fams), seed=0, time_limit=5) == 2
