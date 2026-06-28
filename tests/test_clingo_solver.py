from tests._support import mkfam
from saltshaker.clingo_solver import solve
from saltshaker.constraints import validate
from saltshaker.metrics import measure


def _canon(schedule):
    return [sorted((h.email, tuple(sorted(a.email for a in att)))
                   for h, att in night.items())
            for night in schedule]


def test_trivial_instance_feeds_everyone_and_reconstructs():
    host = mkfam("h@x", space=8, host=[True])
    g1, g2 = mkfam("g1@x"), mkfam("g2@x")
    families = [host, g1, g2]
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == []
    assert measure(families, schedule).unfed_count == 0
    assert schedule[0][host] == {host, g1, g2}


def test_h1_allergic_guest_unfed_when_only_clashing_host():
    host = mkfam("h@x", space=8, allergens=["nuts"], host=[True])  # only host carries nuts
    guest = mkfam("g@x", allergies=["nuts"])
    families = [host, guest]
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == []                 # no H1 violation
    assert ["g@x", 0] in measure(families, schedule).unfed    # guest left unfed, not seated illegally


def test_h2_repel_pair_never_coseated():
    host = mkfam("h@x", space=8, host=[True])
    a = mkfam("a@x", repel=["z"])
    b = mkfam("b@x", repel=["z"])
    families = [host, a, b]
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == []                 # no co-seated repel pair
    assert measure(families, schedule).unfed_count >= 1       # one of a/b cannot be seated


def test_h3_capacity_blocks_oversized_guest():
    host = mkfam("h@x", size=1, space=2, host=[True])         # host uses 1 of 2 seats
    guest = mkfam("g@x", size=2)                              # needs 2, only 1 remains
    families = [host, guest]
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == []
    assert ["g@x", 0] in measure(families, schedule).unfed


def test_h6_host_target_caps_hosting():
    host = mkfam("h@x", space=8, host_target=1, host=[True, True], nights=2)
    guest = mkfam("g@x", nights=2)
    families = [host, guest]
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == []
    assert measure(families, schedule).host_counts.get("h@x", 0) == 1   # hosted at most target


def test_reproducible_under_seed():
    families = [mkfam("h@x", space=8, host=[True]), mkfam("g@x")]
    assert _canon(solve(families, seed=7)) == _canon(solve(families, seed=7))


def test_lp_dump_written(tmp_path):
    lp = tmp_path / "dump.lp"
    solve([mkfam("h@x", space=8, host=[True]), mkfam("g@x")], seed=0, lp_path=str(lp))
    text = lp.read_text()
    assert 'family("h@x").' in text          # facts present
    assert "{ host(F,N) } :- canhost(F,N)." in text  # rules present
