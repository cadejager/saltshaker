# tests/test_asp_objectives.py
import clingo

from tests._support import mkfam
from saltshaker import asp
from saltshaker.balance import compute_cap, pentab_facts


def test_build_facts_emits_knows():
    f = mkfam("h@x", knows=["club"], host=[True])
    assert 'knows("h@x","club").' in asp.build_facts([f])


def test_base_program_grounds_and_feeds_everyone():
    host = mkfam("h@x", space=8, host=[True])
    g1, g2 = mkfam("g1@x"), mkfam("g2@x")
    fams = [host, g1, g2]
    prog = asp.base_program(fams, compute_cap(fams), pentab_facts(fams, T=0))
    ctl = clingo.Control(["--warn=none", "-t", "1"])
    ctl.add("base", [], prog)
    ctl.ground([("base", [])])
    shown = []
    with ctl.solve(yield_=True) as h:
        for m in h:
            shown = m.symbols(shown=True)
    sched = asp.model_to_schedule(shown, fams)
    assert sched[0][host] == {host, g1, g2}   # everyone seated in the one home


def test_cap_rule_present_in_base():
    fams = [mkfam("h@x", space=8, host=[True]), mkfam("g@x")]
    prog = asp.base_program(fams, compute_cap(fams), "")
    assert "cap(7)." in prog
    assert "night(N), cap(Cap)" in prog       # the wasted-seats cap constraint
