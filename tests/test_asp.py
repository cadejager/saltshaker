import clingo

from tests._support import mkfam
from saltshaker.asp import build_facts, build_program, model_to_schedule


def test_facts_include_expected_lines():
    f = mkfam("h@x", size=2, space=5, host=[True])  # host=[True] => canhost night 0
    facts = build_facts([f])
    assert 'family("h@x").' in facts
    assert 'size("h@x",2).' in facts
    assert 'space("h@x",5).' in facts
    assert 'canhost("h@x",0).' in facts
    assert 'canattend("h@x",0).' in facts


def test_tokens_and_target_emitted():
    f = mkfam("h@x", host_target=2, allergies=["nuts"], allergens=["fish"],
              repel=["z"], host=[True])
    facts = build_facts([f])
    assert 'htarget("h@x",2).' in facts
    assert 'allergy("h@x","nuts").' in facts
    assert 'allergen("h@x","fish").' in facts
    assert 'repel("h@x","z").' in facts


def test_build_and_solve_reconstructs_schedule():
    host = mkfam("h@x", space=8, host=[True])
    guest = mkfam("g@x")
    families = [host, guest]
    ctl = clingo.Control(["--warn=none", "-t", "1"])
    ctl.add("base", [], build_program(families))
    ctl.ground([("base", [])])
    shown = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            shown = model.symbols(shown=True)  # last model = optimal
    schedule = model_to_schedule(shown, families)
    assert host in schedule[0]
    assert guest in schedule[0][host]   # guest seated in the host's home
    assert host in schedule[0][host]    # host present in own home (H8)
