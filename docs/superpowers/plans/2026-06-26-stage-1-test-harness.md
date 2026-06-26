# Stage 1 — Test + Metrics Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a solver-independent safety net — a hard-constraint checker, a clean quality-metrics module, a validator CLI, and a pytest suite with committed baselines — that proves every schedule `schedule.py` emits obeys the hard rules and lets us track soft quality across future changes.

**Architecture:** A new `saltshaker/` package holds three pure modules (`constraints.py`, `metrics.py`, `schedule_io.py`) plus a CLI (`validate_cli.py`). They import `Family`/`read_csv`/`find_schedule`/`optimize_schedule` from the existing root `schedule.py` (which is otherwise untouched — its divide-by-zero crash was already patched in commit `3549778`). Tests live in `tests/`, run the real solver in-process over a few trials, assert the hard invariants on every run, and compare aggregate metrics to committed baselines.

**Tech Stack:** Python 3 standard library + `pytest` (dev-only dependency). `dataclasses`, `itertools`, `csv`, `json`, `argparse` from stdlib.

## Global Constraints

- **Python 3** + **`pytest` >= 7** (dev-only; uses the `pythonpath` ini option). No other runtime dependencies.
- **`schedule.py` is not modified by this plan.** The only sanctioned change (the ZeroDivisionError guard, D12) already landed in commit `3549778`. New code *imports from* it.
- **Metrics use clean semantics (D13).** Do NOT reproduce the scoring bugs (self-meetings, double-counted pairs, person-vs-seat unit mix). See Known scoring bugs, §9 of the spec.
- **Do not "fix" original spelling** in identifiers/logs (`summery`, `penility`, `repel`, etc.) — match existing names to avoid breaking references (CLAUDE.md).
- **`Family` identity is its email** (`__eq__`/`__hash__` by email). Compare families with `==`, never `is`.
- **In-memory schedule shape:** `list` indexed by 0-based night; each element a `dict` mapping a host `Family` to a `set` of attendee `Family` objects **including the host**.
- **Branch:** all work on `stage-1-test-harness` (already created off `refactor-roadmap`, which contains the bugfix). Commit after every task.
- Spec reference: `docs/superpowers/specs/2026-06-26-stage-1-test-harness-design.md` (constraints H1–H8 §2, metrics M1–M9 §3).

---

### Task 1: Package scaffolding, pytest config, and in-process solver-run helper

**Files:**
- Create: `saltshaker/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/_support.py` (dependency-free helpers — NO pytest import)
- Create: `conftest.py` (repo root)
- Create: `pytest.ini`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces (in `tests/_support.py`, importable without pytest so `tools/update_baselines.py` can use it):
  - `run_solver(input_csv, time=0, max_dinner_size=8) -> (families: list[Family], schedule: list[dict[Family, set[Family]]])` — runs the real two-stage solver in-process.
  - `mkfam(email, size=1, space=8, host_target=None, allergies=(), allergens=(), knows=(), repel=(), attend=None, host=None, nights=1) -> Family` — hand-builds a `Family` for unit tests (`attend`/`host` default to all-True / all-False of length `nights`).
  - `EXAMPLES` — `pathlib.Path` to `examples/in`.
- Produces (in `conftest.py`): `examples_dir` pytest fixture → `EXAMPLES`.

- [ ] **Step 1: Create the package marker and test package marker**

```bash
mkdir -p saltshaker tests
: > saltshaker/__init__.py
: > tests/__init__.py
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: Create `tests/_support.py` (dependency-free helpers)**

```python
"""Helpers shared by the test suite AND tools/update_baselines.py.

Deliberately imports nothing from pytest, so the baseline tool can run the
solver without pytest installed. `run_solver` runs the real two-stage solver
from schedule.py in-process (no multiprocessing, no file output) so callers can
inspect the produced schedule directly. `time=0` makes each search stage stop
after its first ~1000-iteration batch — fast, but still exercising the real
generate/score/fill code paths.
"""
import argparse
import pathlib

from schedule import read_csv, find_schedule, optimize_schedule, Family

# _support.py lives in tests/, so the repo root is two levels up.
EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples" / "in"


def run_solver(input_csv, time=0, max_dinner_size=8):
    families = read_csv(str(input_csv), max_dinner_size)
    args = argparse.Namespace(time=time)
    host_schedule = find_schedule(args, families)
    schedule = optimize_schedule(args, families, host_schedule, None)
    return families, schedule


def mkfam(email, size=1, space=8, host_target=None, allergies=(), allergens=(),
          knows=(), repel=(), attend=None, host=None, nights=1):
    attend = [True] * nights if attend is None else list(attend)
    host = [False] * nights if host is None else list(host)
    return Family(email, size, space, host_target, frozenset(allergies),
                  frozenset(allergens), frozenset(knows), frozenset(repel),
                  attend, host, sum(attend))
```

- [ ] **Step 4: Create `conftest.py` at the repo root**

```python
"""Pytest config: exposes the examples fixture and quiets the solver's stray
log output. The actual helpers live in tests/_support.py (pytest-free) so
non-test tools can import them too.
"""
import logging

import pytest

from tests._support import EXAMPLES

# find_schedule/optimize_schedule emit log.warning("runs: ...") via the
# multiprocessing logger; silence it so test output stays clean.
logging.getLogger("multiprocessing").setLevel(logging.ERROR)


@pytest.fixture
def examples_dir():
    return EXAMPLES
```

- [ ] **Step 5: Write the smoke test**

```python
# tests/test_smoke.py
from tests._support import run_solver, mkfam


def test_run_solver_returns_schedule(examples_dir):
    families, schedule = run_solver(examples_dir / "a2_in.csv")
    assert isinstance(schedule, list)
    assert len(schedule) == len(families[0].attend_nights)
    # every dinner is a host -> set-of-attendees mapping that includes the host
    for night in schedule:
        for host, attendees in night.items():
            assert host in attendees


def test_mkfam_defaults():
    f = mkfam("a@x", nights=3)
    assert f.email == "a@x"
    assert f.attend_nights == [True, True, True]
    assert f.host_nights == [False, False, False]
    assert f.nights_count == 3
```

- [ ] **Step 6: Run the smoke test and verify it passes**

Run: `pytest tests/test_smoke.py -v`
Expected: 2 passed. (If `import schedule` fails, confirm `pytest.ini` has `pythonpath = .` and you run pytest from the repo root.)

- [ ] **Step 7: Commit**

```bash
git add saltshaker/__init__.py tests/__init__.py tests/_support.py pytest.ini conftest.py tests/test_smoke.py
git commit -m "test: add pytest scaffolding and in-process solver-run helper"
```

---

### Task 2: Hard-constraint checker (`constraints.py`)

**Files:**
- Create: `saltshaker/constraints.py`
- Test: `tests/test_constraints.py`

**Interfaces:**
- Consumes: `mkfam` (Task 1); the in-memory schedule shape.
- Produces:
  - `Violation` — frozen dataclass with fields `rule: str` (`"H1"`..`"H8"`), `night: int` (0-based; `-1` for whole-schedule rules), `emails: tuple[str, ...]`, `message: str`.
  - `validate(families: list[Family], schedule) -> list[Violation]` — empty list means valid. (`families` is accepted for signature stability and future roster checks; the schedule's own `Family` objects carry all data the checks need.)

- [ ] **Step 1: Write failing tests for a clean schedule and each rule H1–H8**

```python
# tests/test_constraints.py
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_constraints.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'saltshaker.constraints'`.

- [ ] **Step 3: Implement `saltshaker/constraints.py`**

```python
"""Hard-constraint checker for saltshaker schedules (Stage-1 spec H1-H8).

Pure and solver-independent: operates on a families list and an in-memory
schedule (list indexed by night; each entry a dict mapping a host Family to the
set of attendee Families, including the host). Returns a list of Violation; an
empty list means the schedule obeys every hard rule.
"""
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class Violation:
    rule: str          # "H1".."H8"
    night: int         # 0-based; -1 for whole-schedule rules (H6)
    emails: tuple      # families involved, by email
    message: str


def validate(families, schedule):
    violations = []

    # H6 is cross-night: tally host counts across the whole schedule first.
    host_counts = {}
    for night_dinners in schedule:
        for host in night_dinners:
            host_counts[host] = host_counts.get(host, 0) + 1
    for host, count in host_counts.items():
        if host.host_target is not None and count > host.host_target:
            violations.append(Violation(
                "H6", -1, (host.email,),
                "%s hosts %d times, exceeds host_target %d"
                % (host.email, count, host.host_target)))

    for night, night_dinners in enumerate(schedule):
        # H7: a family appears in at most one home per night.
        appearances = {}
        for attendees in night_dinners.values():
            for a in attendees:
                appearances[a.email] = appearances.get(a.email, 0) + 1
        for email, n in appearances.items():
            if n > 1:
                violations.append(Violation(
                    "H7", night, (email,),
                    "%s appears in %d homes on night %d" % (email, n, night)))

        for host, attendees in night_dinners.items():
            # H8: the host must attend their own home.
            if host not in attendees:
                violations.append(Violation(
                    "H8", night, (host.email,),
                    "host %s is not in their own home on night %d"
                    % (host.email, night)))

            # H4: host may only host on a Can-Host night.
            if not host.host_nights[night]:
                violations.append(Violation(
                    "H4", night, (host.email,),
                    "%s hosts on night %d but cannot host then"
                    % (host.email, night)))

            # H3: seated people must not exceed the host's capacity (persons).
            seated = sum(a.size for a in attendees)
            if seated > host.space:
                violations.append(Violation(
                    "H3", night, (host.email,),
                    "%s seats %d people, capacity %d on night %d"
                    % (host.email, seated, host.space, night)))

            for a in attendees:
                # H5: every attendee must be available that night.
                if not a.attend_nights[night]:
                    violations.append(Violation(
                        "H5", night, (a.email,),
                        "%s attends night %d but is unavailable"
                        % (a.email, night)))
                # H1: guests (not the host) must not be allergic to the home.
                if a != host and (a.allergies & host.allergens):
                    violations.append(Violation(
                        "H1", night, (a.email, host.email),
                        "%s is allergic to %s's home on night %d"
                        % (a.email, host.email, night)))

            # H2: no co-seated pair (host included) shares a repel token.
            ordered = sorted(attendees, key=lambda f: f.email)
            for a, b in combinations(ordered, 2):
                if a.repel & b.repel:
                    violations.append(Violation(
                        "H2", night, (a.email, b.email),
                        "%s and %s repel but are co-seated on night %d"
                        % (a.email, b.email, night)))

    return violations
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_constraints.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/constraints.py tests/test_constraints.py
git commit -m "feat: add hard-constraint checker (H1-H8)"
```

---

### Task 3: Clean quality-metrics module (`metrics.py`)

**Files:**
- Create: `saltshaker/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `mkfam` (Task 1); the schedule shape.
- Produces:
  - `Metrics` — dataclass with fields: `meals: int`, `dinners: int`, `unfed_count: int`, `unfed: list[list]` (each `[email, night]`), `host_counts: dict[str, int]`, `host_balance: dict | None` (`{"average": float, "max_deviation": float, "ratios": dict[str, float]}`), `new_meetings: int`, `repeat_meetings: int`, `total_empty_seats: int`, `empty_seats: list[int]`, `back_to_back_host_incidents: int`. Method `to_dict() -> dict` (JSON-serializable).
  - `measure(families, schedule) -> Metrics`.

**Clean-semantics rules (do NOT mirror the scoring bugs):**
- A pair is an **unordered** pair of **distinct** families (no self-pairs; each pair counted once).
- `new_meetings` = distinct co-seated pairs whose `knows` sets are **disjoint**.
- `repeat_meetings` = those same disjoint-`knows` pairs co-seated on **≥2 nights**.
- `empty_seats` per dinner = `host.space − sum(attendee.size)` (in **persons**).
- `host_balance` population = flexible families (`host_target is None`) that **hosted ≥1 time**; ratio = `times_hosted / nights_count`. `None` if that population is empty.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.metrics'`.

- [ ] **Step 3: Implement `saltshaker/metrics.py`**

```python
"""Clean quality metrics for saltshaker schedules (Stage-1 spec M1-M9).

These measure real-world quality and deliberately do NOT reproduce the scoring
bugs in schedule.py: no self-meetings, each unordered pair counted once, empty
seats accounted in persons.
"""
from dataclasses import dataclass, asdict
from itertools import combinations


@dataclass
class Metrics:
    meals: int
    dinners: int
    unfed_count: int
    unfed: list
    host_counts: dict
    host_balance: dict  # or None
    new_meetings: int
    repeat_meetings: int
    total_empty_seats: int
    empty_seats: list
    back_to_back_host_incidents: int

    def to_dict(self):
        return asdict(self)


def measure(families, schedule):
    nights = len(schedule)
    fam_by_email = {f.email: f for f in families}

    meals = 0
    dinners = 0
    empty_seats = []
    host_counts = {}
    seated_by_night = [set() for _ in range(nights)]
    pair_nights = {}  # (email_lo, email_hi) -> set of nights co-seated

    for night, night_dinners in enumerate(schedule):
        for host, attendees in night_dinners.items():
            dinners += 1
            host_counts[host.email] = host_counts.get(host.email, 0) + 1
            empty_seats.append(host.space - sum(a.size for a in attendees))
            for a in attendees:
                meals += 1
                seated_by_night[night].add(a.email)
            ordered = sorted(attendees, key=lambda f: f.email)
            for a, b in combinations(ordered, 2):
                pair_nights.setdefault((a.email, b.email), set()).add(night)

    # Meetings: distinct unordered pairs whose knows sets are disjoint.
    new_meetings = 0
    repeat_meetings = 0
    for (e1, e2), ns in pair_nights.items():
        if not (fam_by_email[e1].knows & fam_by_email[e2].knows):
            new_meetings += 1
            if len(ns) > 1:
                repeat_meetings += 1

    # Unfed: available on a night but seated nowhere.
    unfed = []
    for f in families:
        for night in range(nights):
            if f.attend_nights[night] and f.email not in seated_by_night[night]:
                unfed.append([f.email, night])

    # Host balance over flexible hosts that actually hosted.
    ratios = {
        f.email: host_counts[f.email] / f.nights_count
        for f in families
        if f.host_target is None and f.nights_count and f.email in host_counts
    }
    if ratios:
        average = sum(ratios.values()) / len(ratios)
        host_balance = {
            "average": average,
            "max_deviation": max(abs(r - average) for r in ratios.values()),
            "ratios": ratios,
        }
    else:
        host_balance = None

    # Back-to-back hosting incidents (per host-night, matching the penalty shape).
    back_to_back = 0
    for night in range(1, nights):
        prev = set(schedule[night - 1].keys())
        for host in schedule[night]:
            if host in prev:
                back_to_back += 1

    return Metrics(
        meals=meals,
        dinners=dinners,
        unfed_count=len(unfed),
        unfed=unfed,
        host_counts=host_counts,
        host_balance=host_balance,
        new_meetings=new_meetings,
        repeat_meetings=repeat_meetings,
        total_empty_seats=sum(empty_seats),
        empty_seats=empty_seats,
        back_to_back_host_incidents=back_to_back,
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_metrics.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/metrics.py tests/test_metrics.py
git commit -m "feat: add clean quality-metrics module (M1-M9)"
```

---

### Task 4: Output-CSV loader (`schedule_io.py`)

**Files:**
- Create: `saltshaker/schedule_io.py`
- Test: `tests/test_schedule_io.py`

**Interfaces:**
- Consumes: `read_csv` from `schedule.py`.
- Produces:
  - `OutputCsvError(Exception)`.
  - `load_output_csv(input_csv, output_csv) -> (families: list[Family], schedule, warnings: list[str])`. Reconstruction rules (spec §4c): night count from the input; all input families retained; host capacity taken from the output CSV `Space` column (each host's `Family.space` is overwritten with it); duplicate `(night, host)` rows and unknown emails raise `OutputCsvError`; a host missing from its own attendee list is added and recorded in `warnings`.

- [ ] **Step 1: Write failing tests (build tiny CSVs in `tmp_path`)**

```python
# tests/test_schedule_io.py
import pytest
from saltshaker.schedule_io import load_output_csv, OutputCsvError

INPUT = (
    "email,size,space,ht,al,ag,kn,rp,n1\n"
    "h@x,1,8,,,,,,Can Host\n"
    "g@x,2,8,,,,,,Can Attend\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_loads_basic_schedule(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    families, schedule, warnings = load_output_csv(inp, out)
    assert warnings == []
    assert len(schedule) == 1
    [(host, attendees)] = schedule[0].items()
    assert host.email == "h@x"
    assert {a.email for a in attendees} == {"h@x", "g@x"}


def test_host_capacity_comes_from_output_space(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,5,h@x,"h@x, g@x"\n')  # Space=5 differs from input 8
    _families, schedule, _ = load_output_csv(inp, out)
    [(host, _att)] = schedule[0].items()
    assert host.space == 5


def test_unknown_attendee_raises(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, ghost@x"\n')
    with pytest.raises(OutputCsvError):
        load_output_csv(inp, out)


def test_host_missing_from_attendees_warns_and_is_added(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,2,8,h@x,"g@x"\n')  # host omitted
    _families, schedule, warnings = load_output_csv(inp, out)
    [(host, attendees)] = schedule[0].items()
    assert host in attendees
    assert any("missing from own attendee" in w for w in warnings)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_schedule_io.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.schedule_io'`.

- [ ] **Step 3: Implement `saltshaker/schedule_io.py`**

```python
"""Reconstruct an in-memory schedule from saltshaker's output CSV.

Used by the validator CLI to audit arbitrary / hand-edited output files. The
input CSV is parsed with schedule.read_csv to recover family attributes; the
output CSV supplies the per-night host->attendees assignment and the host
capacity (Space column), so an audit is self-contained.
"""
import csv
import sys

from schedule import read_csv


class OutputCsvError(Exception):
    pass


def load_output_csv(input_csv, output_csv):
    families = read_csv(input_csv, sys.maxsize)  # huge cap => no clamping
    by_email = {f.email: f for f in families}
    nights = len(families[0].attend_nights) if families else 0

    schedule = [{} for _ in range(nights)]
    warnings = []

    with open(output_csv, newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # skip header
        for row in reader:
            night = int(row[0])
            space = int(row[2])
            host_email = row[3]
            attendee_emails = [e.strip() for e in row[4].split(",") if e.strip()]

            if night < 0 or night >= nights:
                raise OutputCsvError(
                    "row night %d out of range 0..%d" % (night, nights - 1))
            if host_email not in by_email:
                raise OutputCsvError("unknown host email: %s" % host_email)
            host = by_email[host_email]
            host.space = space  # trust the output CSV's recorded capacity

            if host in schedule[night]:
                raise OutputCsvError(
                    "duplicate dinner for host %s on night %d"
                    % (host_email, night))

            attendees = set()
            for email in attendee_emails:
                if email not in by_email:
                    raise OutputCsvError("unknown attendee email: %s" % email)
                attendees.add(by_email[email])
            if host not in attendees:
                warnings.append(
                    "host %s missing from own attendee list (night %d)"
                    % (host_email, night))
                attendees.add(host)
            schedule[night][host] = attendees

    return families, schedule, warnings
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_schedule_io.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/schedule_io.py tests/test_schedule_io.py
git commit -m "feat: add output-CSV loader for auditing schedules"
```

---

### Task 5: Validator CLI (`validate_cli.py`)

**Files:**
- Create: `saltshaker/validate_cli.py`
- Test: `tests/test_validate_cli.py`

**Interfaces:**
- Consumes: `validate` (Task 2), `measure` (Task 3), `load_output_csv`/`OutputCsvError` (Task 4).
- Produces: `main(argv=None) -> int` (exit code). `0` = no violations, `1` = violations found, `2` = malformed input. With `--metrics`, prints `measure(...).to_dict()` as JSON to stdout. Runnable as `python -m saltshaker.validate_cli INPUT OUTPUT [--metrics]`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_validate_cli.py
from saltshaker.validate_cli import main

INPUT = (
    "email,size,space,ht,al,ag,kn,rp,n1\n"
    "h@x,1,8,,,,,,Can Host\n"
    "g@x,2,8,,,,,,Can Attend\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_clean_schedule_exits_zero(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    assert main([inp, out]) == 0


def test_capacity_violation_exits_one(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,2,h@x,"h@x, g@x"\n')  # 3 people, Space=2 -> H3
    assert main([inp, out]) == 1


def test_malformed_exits_two(tmp_path):
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,nobody@x,"nobody@x"\n')  # unknown host
    assert main([inp, out]) == 2


def test_metrics_flag_prints_json(tmp_path, capsys):
    import json
    inp = _write(tmp_path, "in.csv", INPUT)
    out = _write(tmp_path, "out.csv",
                 "Night,Size,Space,Host,Attendees\n"
                 '0,3,8,h@x,"h@x, g@x"\n')
    main([inp, out, "--metrics"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["meals"] == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest tests/test_validate_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.validate_cli'`.

- [ ] **Step 3: Implement `saltshaker/validate_cli.py`**

```python
"""CLI: audit an (input.csv, output.csv) schedule pair against H1-H8.

    python -m saltshaker.validate_cli INPUT.csv OUTPUT.csv [--metrics]

Exit status: 0 = clean, 1 = hard-constraint violations found, 2 = malformed input.
"""
import argparse
import json
import sys

from saltshaker.constraints import validate
from saltshaker.metrics import measure
from saltshaker.schedule_io import load_output_csv, OutputCsvError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit a saltshaker schedule")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--metrics", action="store_true",
                        help="also print quality metrics as JSON to stdout")
    args = parser.parse_args(argv)

    try:
        families, schedule, warnings = load_output_csv(args.input, args.output)
    except OutputCsvError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2

    for w in warnings:
        print("WARNING: %s" % w, file=sys.stderr)

    violations = validate(families, schedule)
    for v in violations:
        print("%s night %s: %s" % (v.rule, v.night, v.message), file=sys.stderr)

    if args.metrics:
        print(json.dumps(measure(families, schedule).to_dict(),
                         indent=2, sort_keys=True))

    if violations:
        print("%d violation(s)" % len(violations), file=sys.stderr)
        return 1
    print("OK: no hard-constraint violations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `pytest tests/test_validate_cli.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/validate_cli.py tests/test_validate_cli.py
git commit -m "feat: add validator CLI for auditing schedule CSVs"
```

---

### Task 6: Baseline generator + example integration tests

**Files:**
- Create: `tools/update_baselines.py`
- Create: `tests/baselines/.gitkeep` (then generated `*.json`)
- Test: `tests/test_examples.py`

**Interfaces:**
- Consumes: `run_solver` (Task 1), `validate` (Task 2), `measure` (Task 3).
- Baseline JSON shape (one file per input, e.g. `tests/baselines/a2_in.json`):
  ```json
  {"trials": 5, "time": 0,
   "meals": {"min": <int>, "max": <int>, "floor": <int>},
   "unfed_count": {"min": <int>, "max": <int>, "ceiling": <int>},
   "new_meetings": {"min": <int>, "max": <int>},
   "dinners": {"min": <int>, "max": <int>}}
  ```
  `floor = int(meals_min * 0.8)`; `ceiling = unfed_max + max(2, unfed_max)` (generous, so a slower box can't flake; only a *worsening* of starvation trips it).

**Why these are the asserted quantities:** `meals` (people fed) and `unfed_count` are the most stable, most meaningful signals and map directly to the soon-to-be-hard "feed everyone" goal (D2a). `new_meetings`/`dinners` are recorded for visibility but not asserted (too volatile on an unseeded solver — see spec §5c).

- [ ] **Step 1: Create the baselines directory placeholder**

```bash
mkdir -p tests/baselines
: > tests/baselines/.gitkeep
```

- [ ] **Step 2: Write `tools/update_baselines.py`**

```python
#!/usr/bin/env python3
"""Regenerate tests/baselines/<input>.json by running the solver N times.

Run from the repo root:  python tools/update_baselines.py
Commit the resulting JSON so quality changes show up as reviewable diffs.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests._support import run_solver  # noqa: E402
from saltshaker.constraints import validate  # noqa: E402
from saltshaker.metrics import measure  # noqa: E402

INPUTS = ["a2_in.csv", "anonymised_in.csv", "example_in.csv"]
TRIALS = 5
TIME = 0
ROOT = pathlib.Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "in"
OUT = ROOT / "tests" / "baselines"


def _agg(values):
    return {"min": min(values), "max": max(values)}


def build(name):
    meals, unfed, meets, dinners = [], [], [], []
    for _ in range(TRIALS):
        families, schedule = run_solver(EX / name, time=TIME)
        assert validate(families, schedule) == [], "%s produced a violation" % name
        m = measure(families, schedule)
        meals.append(m.meals)
        unfed.append(m.unfed_count)
        meets.append(m.new_meetings)
        dinners.append(m.dinners)
    data = {"trials": TRIALS, "time": TIME,
            "meals": {**_agg(meals), "floor": int(min(meals) * 0.8)},
            "unfed_count": {**_agg(unfed), "ceiling": max(unfed) + max(2, max(unfed))},
            "new_meetings": _agg(meets),
            "dinners": _agg(dinners)}
    (OUT / name.replace(".csv", ".json")).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("wrote baseline for", name)


if __name__ == "__main__":
    for n in INPUTS:
        build(n)
```

- [ ] **Step 3: Generate the baselines and eyeball them**

Run: `python tools/update_baselines.py`
Expected: prints "wrote baseline for ..." three times; creates `tests/baselines/{a2_in,anonymised_in,example_in}.json`. Open one and sanity-check (e.g. `meals.min` > 0, `floor` < `min`).

- [ ] **Step 4: Write `tests/test_examples.py`**

```python
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
```

- [ ] **Step 5: Run the full suite and verify it passes**

Run: `pytest -v`
Expected: every test PASSES across all modules (full suite ~50–70s; the example tests run the solver 15×). If `test_example_invariants_and_quality` is flaky on quality, the floor/ceiling margins in `tools/update_baselines.py` are too tight — widen them, regenerate, and re-run. (Per the independent review, `meals`/`unfed` are effectively deterministic across trials, so this should not happen.)

- [ ] **Step 6: Commit**

```bash
git add tools/update_baselines.py tests/test_examples.py tests/baselines/
git commit -m "test: add example integration tests with committed quality baselines"
```

---

### Task 7: Document the harness in the README

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only). Fold into this task because the harness isn't "done" until a newcomer can run it.

- [ ] **Step 1: Append a "Testing & auditing" section to `README.md`**

```markdown
## Testing & auditing

Install the test dependency and run the suite from the repo root:

    pip install pytest
    pytest

Audit any input/output CSV pair by hand:

    python -m saltshaker.validate_cli examples/in/a2_in.csv examples/out/a2_out.csv --metrics

Regenerate the committed quality baselines after an intentional change:

    python tools/update_baselines.py
```

- [ ] **Step 2: Verify the documented commands actually work**

Run: `pytest -q` and the `validate_cli` command above.
Expected: suite passes; the CLI prints metrics JSON and `OK: no hard-constraint violations`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the test harness and validator CLI"
```

---

## Self-review notes

- **Spec coverage:** 1a→Task 2, 1b→Task 3, schedule_io→Task 4, 1d→Task 5, 1c→Tasks 1+6, baselines/update script→Task 6, Task 1.0 crash patch→already done (regression test in Task 6). H1–H8 each have a unit test (Task 2); M1–M9 covered by Task 3 + integration. Validator reconstruction rules (B1–B3), unfed ceiling (Q5), and margins (Q3) are in Task 4/Task 6.
- **Out of scope (unchanged here):** no clingo, no JSON instance/schedule formats, no run-report, no `--seed`, no scoring-bug fixes, no edits to `schedule.py`.
- **Type consistency:** `validate(families, schedule) -> list[Violation]`; `measure(families, schedule) -> Metrics` with `to_dict()`; `load_output_csv(...) -> (families, schedule, warnings)`; CLI `main(argv) -> int`. These names are used identically across Tasks 2–6.
- **Open tuning (safe to adjust during execution):** `TRIALS` (default 5) and `time=0`; baseline floor/ceiling margins. Widen if CI flakes.
- **Independent-review note (verified, non-blocking):** an agent replicated and ran every module against the real `schedule.py` — zero blocking bugs, all unit tests pass, `meals`/`unfed` effectively deterministic across trials. Two findings were folded in: helpers moved to `tests/_support.py` (so the baseline tool doesn't need pytest), and the two example tests merged into one (15 solver runs, not 30).
- **Latent H3 edge for FUTURE inputs (not the committed three):** `generate_host_schedule` seeds a host into their own home unconditionally, even if `space < size`. None of the three example inputs has a `Can Host` family with `space < size`, so the checker sees zero violations today. But if someone later adds such an input, the solver will emit a host-only dinner that legitimately trips **H3** — that's the checker working correctly (it's a solver/data issue, not a false positive). Flagging so a future input-adder isn't surprised.
