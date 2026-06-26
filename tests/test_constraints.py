from tests._support import mkfam
from saltshaker.constraints import validate


def _rules(violations):
    return sorted(v.rule for v in violations)


def test_clean_schedule_has_no_violations():
    h = mkfam("h@x", space=8, host=[True])
    g = mkfam("g@x", size=2)
    schedule = [{h: {h, g}}]
    assert validate([h, g], schedule) == []


def test_h1_guest_allergic_to_home():
    h = mkfam("h@x", space=8, host=[True], allergens=["nuts"])
    g = mkfam("g@x", allergies=["nuts"])
    assert "H1" in _rules(validate([h, g], [{h: {h, g}}]))


def test_h1_ignores_host_against_own_home():
    # host carries an allergen AND the matching allergy; must NOT be flagged H1
    h = mkfam("h@x", space=8, host=[True], allergens=["nuts"], allergies=["nuts"])
    assert "H1" not in _rules(validate([h], [{h: {h}}]))


def test_h2_repel_pair_coseated():
    h = mkfam("h@x", space=8, host=[True])
    a = mkfam("a@x", repel=["z"])
    b = mkfam("b@x", repel=["z"])
    assert "H2" in _rules(validate([h, a, b], [{h: {h, a, b}}]))


def test_h3_capacity_exceeded():
    h = mkfam("h@x", space=2, host=[True])
    g = mkfam("g@x", size=5)
    assert "H3" in _rules(validate([h, g], [{h: {h, g}}]))


def test_h4_host_on_non_host_night():
    h = mkfam("h@x", space=8, host=[False])  # cannot host
    assert "H4" in _rules(validate([h], [{h: {h}}]))


def test_h5_attendee_unavailable():
    h = mkfam("h@x", space=8, host=[True])
    g = mkfam("g@x", attend=[False])  # not available night 0
    assert "H5" in _rules(validate([h, g], [{h: {h, g}}]))


def test_h6_exceeds_host_target():
    h = mkfam("h@x", space=8, host_target=1, host=[True, True], nights=2)
    schedule = [{h: {h}}, {h: {h}}]  # hosts twice, target 1
    assert "H6" in _rules(validate([h], schedule))


def test_h7_family_in_two_homes_one_night():
    h1 = mkfam("h1@x", space=8, host=[True])
    h2 = mkfam("h2@x", space=8, host=[True])
    g = mkfam("g@x")
    schedule = [{h1: {h1, g}, h2: {h2, g}}]  # g seated twice
    assert "H7" in _rules(validate([h1, h2, g], schedule))


def test_h8_host_missing_from_own_home():
    h = mkfam("h@x", space=8, host=[True])
    g = mkfam("g@x")
    schedule = [{h: {g}}]  # host not present
    assert "H8" in _rules(validate([h, g], schedule))
