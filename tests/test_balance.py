# tests/test_balance.py
from tests._support import mkfam
from saltshaker.balance import hostable, flexible_hosts, compute_cap, fairshare_targets, pentab_facts


def test_hostable_and_flexible():
    h = mkfam("h@x", space=8, host=[True, False], nights=2)          # can host
    t = mkfam("t@x", space=6, host_target=2, host=[True, True], nights=2)  # targeted host
    g = mkfam("g@x", host=[False, False], nights=2)                  # never hosts
    fams = [h, t, g]
    assert {f.email for f in hostable(fams)} == {"h@x", "t@x"}
    assert {f.email for f in flexible_hosts(fams)} == {"h@x"}        # t has a target


def test_compute_cap_ignores_non_hosting_big_space():
    h = mkfam("h@x", space=8, host=[True])
    big = mkfam("big@x", space=20, host=[False])                     # huge space, never hosts
    assert compute_cap([h, big]) == 7                                # max(8) - 1, big ignored


def test_fairshare_targets_proportional_to_attendance():
    a = mkfam("a@x", host=[True, True, True, True], attend=[True, True, True, True], nights=4)
    b = mkfam("b@x", host=[True, True, True, True], attend=[True, True, False, False], nights=4)
    # A = 4 + 2 = 6; T = 6 -> a: round(10*6*4/6)=40, b: round(10*6*2/6)=20
    tgt = fairshare_targets([a, b], T=6)
    assert tgt == {"a@x": 40, "b@x": 20}


def test_pentab_facts_shape():
    a = mkfam("a@x", host=[True, True], attend=[True, True], nights=2)
    facts = pentab_facts([a], T=2)   # A=2, S10 = round(10*2*2/2)=20
    assert 'pentab("a@x",0,20).' in facts   # |0-20|
    assert 'pentab("a@x",2,0).' in facts    # |20-20|
    assert 'pentab("a@x",1,10).' in facts    # |10-20|


def test_synthetic_many_flexible_hosts_balance():
    # 6 flexible hosts with VARIED availability + 6 guests over 4 nights.
    from saltshaker.clingo_solver import solve_optimized
    from saltshaker.constraints import validate
    from saltshaker.metrics import measure
    fams = []
    for i in range(6):
        att = [True] * (2 + i % 3)             # attend 2,3,4,2,3,4 nights
        att += [False] * (4 - len(att))
        fams.append(mkfam("h%d@x" % i, size=1, space=6, host=att, attend=att, nights=4))
    for i in range(6):
        fams.append(mkfam("g%d@x" % i, size=1, host=[False] * 4, attend=[True] * 4, nights=4))
    sched = solve_optimized(fams, seed=0, time_limit=8)
    assert validate(fams, sched) == []
    assert measure(fams, sched).unfed_count == 0
    hb = measure(fams, sched).host_balance
    assert hb is not None and hb["max_deviation"] <= 0.35   # reasonably even given the setup
