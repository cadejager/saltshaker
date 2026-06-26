# tests/test_metrics.py
from tests._support import mkfam
from saltshaker.metrics import measure


def test_basic_counts_and_clean_pairs():
    h = mkfam("h@x", size=1, space=8, host=[True])
    g1 = mkfam("g1@x", size=2)
    g2 = mkfam("g2@x", size=1)
    families = [h, g1, g2]
    schedule = [{h: {h, g1, g2}}]
    m = measure(families, schedule)

    assert m.meals == 3
    assert m.dinners == 1
    assert m.total_empty_seats == 8 - (1 + 2 + 1)  # persons, == 4
    # distinct unordered pairs: {h,g1},{h,g2},{g1,g2}; no self-pairs
    assert m.new_meetings == 3
    assert m.repeat_meetings == 0
    assert m.unfed_count == 0
    assert m.host_counts == {"h@x": 1}
    assert m.host_balance["average"] == 1.0
    assert m.host_balance["max_deviation"] == 0.0
    assert m.back_to_back_host_incidents == 0


def test_knows_suppresses_new_meeting():
    h = mkfam("h@x", space=8, host=[True])
    g1 = mkfam("g1@x", knows=["club"])
    g2 = mkfam("g2@x", knows=["club"])  # g1 & g2 already know each other
    m = measure([h, g1, g2], [{h: {h, g1, g2}}])
    # {g1,g2} suppressed; {h,g1} and {h,g2} still count
    assert m.new_meetings == 2


def test_repeat_meeting_across_nights():
    h = mkfam("h@x", space=8, host=[True, True], nights=2)
    g = mkfam("g@x", nights=2)
    schedule = [{h: {h, g}}, {h: {h, g}}]
    m = measure([h, g], schedule)
    assert m.new_meetings == 1          # the {h,g} pair
    assert m.repeat_meetings == 1       # met on both nights


def test_unfed_lists_available_but_unseated():
    h = mkfam("h@x", space=8, host=[True], nights=1)
    g = mkfam("g@x", nights=1)          # available night 0 but never seated
    schedule = [{h: {h}}]
    m = measure([h, g], schedule)
    assert m.unfed_count == 1
    assert ["g@x", 0] in m.unfed


def test_to_dict_is_json_serializable():
    import json
    h = mkfam("h@x", space=8, host=[True])
    m = measure([h], [{h: {h}}])
    json.dumps(m.to_dict())  # must not raise
