# Clingo Objectives (One-Stage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the clingo solver produce *good* schedules — proven-optimal host-balance, maximized mixing, everyone fed — beating the committed baselines, via a one-stage two-pass solve with a hard wasted-seats cap.

**Architecture:** A new `solve_optimized()` runs one clingo `Control` grounded in two steps: an aux min-dinners solve anchors a coarse fair-share balance target; Pass 1 proves the host-balance optimum; then mixing/back-to-back rules and a balance-cost lock are grounded in and Pass 2 maximizes mixing best-found. A hard per-night wasted-seats cap prevents over-hosting. Phase-1's feasibility `solve()` and its tests are left intact (retired in 2b).

**Tech Stack:** Python 3, `clingo==5.8.0` (in-process, multi-shot + async solve), `pytest`. Run via `uv run`.

## Global Constraints

- Run tests with **`uv run pytest`**, the tool with **`uv run python -m saltshaker.cli ...`**. No pip on this box.
- **Do NOT modify** `schedule.py`, `saltshaker/{constraints,metrics,schedule_io,validate_cli}.py`, or any **phase-1** test (`test_asp.py` existing tests, `test_clingo_solver.py`, `test_clingo_feasibility.py`, `test_cli_clingo.py`). Phase-1 `clingo_solver.solve()` stays as-is (feasibility, weak feed). This phase ADDS `solve_optimized()` and new tests; `cli.py` switches to it. (Retiring the old solver is 2b.)
- **Emails/tokens are double-quoted ASP strings** (`asp._q`).
- **Objective priority:** feed-everyone (HARD `:- canattend(G,N), not host(G,N), not seat(G,_,N).`) and the wasted-seats cap are HARD; then `@3` host-balance, `@2` mixing, `@1` back-to-back.
- **Wasted-seats cap** `Cap = max(space) − 1` over families that can host on ≥1 night. Hard, per night.
- **Coarse balance:** penalty table `pentab(F,C,P)`, `P = |10*C − round(10*T*attend(F)/A)|` — provable. Do NOT use a finer/ratio-scaled encoding (unprovable, stalls).
- **Grounding order is load-bearing:** ground base (facts+cap+balance) for Pass 1; mixing/b2b/lock are grounded ONLY after Pass 1 proves the balance optimum. Grounding mixing before Pass 1 makes balance un-provable (stalls at ~0.35).
- **`--time-limit` is not a clingo `Control` option** — bound solves with `ctl.solve(async_=True)` + `handle.wait(t)` / `handle.cancel()`.
- **Determinism:** balance is proven (bit-stable under `--seed` + `-t 1`); mixing + aux `T` are best-found within a budget (machine-sensitive) → tests use floors-with-margin.
- `Family` identity is its email; schedule shape is `list` by night of `dict` host`Family`→`set` attendee `Family`.
- Spec: `docs/superpowers/specs/2026-06-29-clingo-objectives-design.md`.

---

### Task 1: Balance helpers (`balance.py`)

**Files:**
- Create: `saltshaker/balance.py`
- Test: `tests/test_balance.py`

**Interfaces:**
- Consumes: `Family` fields (`space`, `host_nights`, `host_target`, `attend_nights`, `email`).
- Produces:
  - `hostable(families) -> list[Family]` — families that can host ≥1 night.
  - `flexible_hosts(families) -> list[Family]` — hostable with `host_target is None`.
  - `compute_cap(families) -> int` — `max(space of hostable) − 1`.
  - `fairshare_targets(families, T) -> dict[str, int]` — `email -> round(10*T*attend/A)` over flexible hosts.
  - `pentab_facts(families, T) -> str` — ASP `pentab("email",C,P).` lines for each flexible host, `C in 0..nights`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_balance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.balance'`.

- [ ] **Step 3: Implement `saltshaker/balance.py`**

```python
"""Host-balance helpers for the objectives solver: the wasted-seats cap, the
availability-proportional fair-share target, and the coarse penalty table.
Pure (no clingo). See 2026-06-29-clingo-objectives-design.md."""


def hostable(families):
    """Families that can host on at least one night."""
    return [f for f in families if any(f.host_nights)]


def flexible_hosts(families):
    """Hostable families with no host_target (their hosting ratio is balanced)."""
    return [f for f in families if any(f.host_nights) and f.host_target is None]


def compute_cap(families):
    """Wasted-seats cap = (max space among hostable families) - 1.

    Only families that can actually host count, so a large-space family that
    never hosts cannot inflate the cap.
    """
    return max(f.space for f in hostable(families)) - 1


def fairshare_targets(families, T):
    """email -> round(10 * T * attend(F) / A) over flexible hosts (integer tenths),
    A = sum of attend-night counts over flexible hosts. Empty if no flexible hosts."""
    flex = flexible_hosts(families)
    total_attend = sum(sum(f.attend_nights) for f in flex)
    targets = {}
    for f in flex:
        att = sum(f.attend_nights)
        targets[f.email] = round(10 * T * att / total_attend) if total_attend else 0
    return targets


def pentab_facts(families, T):
    """ASP facts pentab("email",C,P) for each flexible host and each count
    C in 0..nights, P = |10*C - fairshare|. Empty string if no flexible hosts."""
    flex = flexible_hosts(families)
    if not flex:
        return ""
    nights = len(families[0].attend_nights)
    targets = fairshare_targets(families, T)
    lines = []
    for f in flex:
        s10 = targets[f.email]
        for c in range(nights + 1):
            lines.append('pentab("%s",%d,%d).' % (f.email, c, abs(10 * c - s10)))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_balance.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/balance.py tests/test_balance.py
git commit -m "feat: add host-balance helpers (cap, fair-share, pentab)"
```

---

### Task 2: Objectives ASP parts + program builders (`asp.py`)

**Files:**
- Modify: `saltshaker/asp.py` (add new constants/functions; leave phase-1 `RULES`/`build_program`/`build_facts`/`model_to_schedule` intact except the `knows` addition to `build_facts`)
- Test: `tests/test_asp_objectives.py`

**Interfaces:**
- Consumes: `balance.pentab_facts` (Task 1); phase-1 `build_facts`/`model_to_schedule`.
- Produces (in `asp.py`):
  - Constants: `HARD_CORE`, `CAP_RULE`, `BALANCE_RULES`, `MIXING_B2B_RULES`, `SHOW`, `LOCK_PROGRAM` (the body for `#program lock(cb).`).
  - `aux_program(families, cap) -> str` — facts + hard core + cap + minimize-dinners + show. (No balance/mixing.)
  - `base_program(families, cap, pentab) -> str` — facts + hard core + cap + `cap(Cap).` + pentab facts + balance rules + show. (Pass-1 base.)
- Also: `build_facts` now emits `knows(...)` facts.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_asp_objectives.py -v`
Expected: FAIL — `AttributeError: module 'saltshaker.asp' has no attribute 'base_program'` (and `knows` assertion fails).

- [ ] **Step 3: Modify `saltshaker/asp.py`**

Add the `knows` emission inside `build_facts`, in the per-family loop next to the other token loops:

```python
        for t in f.knows:
            lines.append("knows(%s,%s)." % (e, _q(t)))
```

Append the following constants and builders at the end of the module:

```python
# --- Phase 2a: one-stage objectives program parts ---
# Hard constraints H1-H8, with feed-everyone HARD (a direct integrity constraint).
HARD_CORE = """
{ host(F,N) } :- canhost(F,N).
seat(F,F,N) :- host(F,N).
{ seat(G,H,N) : host(H,N) } 1 :- canattend(G,N), not host(G,N).

:- host(H,N), space(H,Sp), #sum { S,G : seat(G,H,N), size(G,S) } > Sp.
:- seat(G,H,N), G != H, allergy(G,T), allergen(H,T).
:- seat(A,H,N), seat(B,H,N), A < B, repel(A,T), repel(B,T).
:- htarget(F,T), #count { N : host(F,N) } > T.

:- canattend(G,N), not host(G,N), not seat(G,_,N).
"""

# Hard wasted-seats cap: total empty seats per night <= Cap.
CAP_RULE = """
:- night(N), cap(Cap),
   #sum { Sp,H : host(H,N), space(H,Sp) ; -S,G : seat(G,H,N), size(G,S) } > Cap.
"""

# Coarse host-balance (@3). pentab facts are emitted from Python.
BALANCE_RULES = """
flexible(F) :- canhost(F,_), not htarget(F,_).
hostcnt(F,C) :- flexible(F), C = #count { N : host(F,N) }.
balpen(F,P)  :- hostcnt(F,C), pentab(F,C,P).
:~ balpen(F,P). [P@3, F]
"""

# Mixing (@2, = metric M5) and back-to-back (@1). Grounded for Pass 2 only.
MIXING_B2B_RULES = """
sharedknows(A,B) :- knows(A,T), knows(B,T), A < B.
meet(A,B) :- seat(A,H,N), seat(B,H,N), A < B, not sharedknows(A,B).
:~ meet(A,B). [-1@2, A, B]
b2b(F,N) :- host(F,N), host(F,N-1).
:~ b2b(F,N). [1@1, F, N]
"""

SHOW = """
#show host/2.
#show seat/3.
"""

# Balance-cost lock body for `#program lock(cb).` (grounded after Pass 1).
LOCK_PROGRAM = ":- #sum { P,F : balpen(F,P) } > cb."


def aux_program(families, cap):
    """Min-dinners program (to anchor the fair-share target T): hard core + cap +
    minimize total dinners. No balance/mixing."""
    return (asp_join(build_facts(families), "cap(%d)." % cap, HARD_CORE, CAP_RULE,
                     ":~ host(F,N). [1@1, F, N]", "#show host/2."))


def base_program(families, cap, pentab):
    """Pass-1 base: hard core + cap + coarse balance. Mixing/b2b are added later."""
    return asp_join(build_facts(families), "cap(%d)." % cap, pentab,
                    HARD_CORE, CAP_RULE, BALANCE_RULES, SHOW)


def asp_join(*parts):
    """Join non-empty program fragments with newlines."""
    return "\n".join(p for p in parts if p) + "\n"
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_asp_objectives.py -v`
Also run the phase-1 asp tests to confirm no regression: `uv run pytest tests/test_asp.py -v`
Expected: new tests pass (3); phase-1 `test_asp.py` still passes (the `knows` addition only adds fact lines).

- [ ] **Step 5: Commit**

```bash
git add saltshaker/asp.py tests/test_asp_objectives.py
git commit -m "feat: add one-stage objectives ASP parts and program builders"
```

---

### Task 3: Bounded-solve helper + aux target `T` (`clingo_solver.py`)

**Files:**
- Modify: `saltshaker/clingo_solver.py` (add functions; leave phase-1 `solve` intact)
- Test: `tests/test_solver_helpers.py`

**Interfaces:**
- Consumes: `asp.aux_program` (Task 2), `balance.flexible_hosts` (Task 1).
- Produces:
  - `_solve_bounded(ctl, time_limit) -> (symbols|None, cost|None, exhausted: bool)` — solve `ctl`, optionally bounded (seconds) via async-cancel, capturing the best model.
  - `compute_target(families, cap, seed=0, time_limit=10) -> int` — best-found flexible host-slot demand `T` from the aux min-dinners solve; `0` if no flexible hosts.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_solver_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_target'`.

- [ ] **Step 3: Add to `saltshaker/clingo_solver.py`** (append; keep the existing `solve`)

```python
from saltshaker import balance  # add near the top imports


def _solve_bounded(ctl, time_limit):
    """Solve `ctl`, capturing the best (last) model's shown symbols and cost.

    If time_limit (seconds) is given, bound the search with async solve + cancel
    (clingo has no --time-limit Control option). Returns (symbols, cost, exhausted).
    """
    best = {"symbols": None, "cost": None}

    def on_model(model):
        best["symbols"] = model.symbols(shown=True)
        best["cost"] = list(model.cost)

    if time_limit is None:
        result = ctl.solve(on_model=on_model)
    else:
        with ctl.solve(on_model=on_model, async_=True) as handle:
            if not handle.wait(time_limit):
                handle.cancel()
            result = handle.get()
    return best["symbols"], best["cost"], result.exhausted


def compute_target(families, cap, seed=0, time_limit=10):
    """Best-found flexible host-slot demand T from the aux min-dinners solve.
    Returns 0 when there are no flexible hosts (the aux + balance layer is skipped)."""
    flex_emails = {f.email for f in balance.flexible_hosts(families)}
    if not flex_emails:
        return 0
    ctl = clingo.Control(["--warn=none", "--seed=%d" % seed, "-t", "1"])
    ctl.add("base", [], asp.aux_program(families, cap))
    ctl.ground([("base", [])])
    symbols, _cost, _exhausted = _solve_bounded(ctl, time_limit)
    if symbols is None:
        raise RuntimeError("aux min-dinners solve found no model")
    return sum(1 for s in symbols
               if s.name == "host" and s.arguments[0].string in flex_emails)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_solver_helpers.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/clingo_solver.py tests/test_solver_helpers.py
git commit -m "feat: add bounded-solve helper and aux fair-share target"
```

---

### Task 4: Two-pass objectives solver (`solve_optimized`)

**Files:**
- Modify: `saltshaker/clingo_solver.py` (add `solve_optimized`)
- Test: `tests/test_solve_optimized.py`

**Interfaces:**
- Consumes: `_solve_bounded`, `compute_target` (Task 3); `asp.base_program`/`MIXING_B2B_RULES`/`LOCK_PROGRAM`/`model_to_schedule` (Task 2); `balance.compute_cap`/`pentab_facts`/`flexible_hosts` (Task 1).
- Produces: `solve_optimized(families, seed=0, time_limit=60, aux_time_limit=10, balance_time_limit=30, lp_path=None) -> schedule`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_solve_optimized.py -v`
Expected: FAIL — `ImportError: cannot import name 'solve_optimized'`.

- [ ] **Step 3: Add `solve_optimized` to `saltshaker/clingo_solver.py`**

```python
def solve_optimized(families, seed=0, time_limit=60, aux_time_limit=10,
                    balance_time_limit=30, lp_path=None):
    """One-stage two-pass objectives solve. Returns the best schedule found.

    Pass 1 proves the coarse host-balance optimum on the base program (facts + cap
    + balance); then mixing/back-to-back rules and a balance-cost lock are grounded
    in and Pass 2 maximizes mixing within the remaining budget. Balance is proven
    (deterministic); mixing is best-found. See the objectives spec.
    """
    cap = balance.compute_cap(families)
    target = compute_target(families, cap, seed=seed, time_limit=aux_time_limit)
    pentab = balance.pentab_facts(families, target)
    base_prog = asp.base_program(families, cap, pentab)

    if lp_path is not None:
        with open(lp_path, "w") as fh:
            fh.write(base_prog + "\n" + asp.MIXING_B2B_RULES + "\n"
                     + "#program lock(cb).\n" + asp.LOCK_PROGRAM + "\n")

    ctl = clingo.Control(["--warn=none", "--seed=%d" % seed, "-t", "1"])
    ctl.add("base", [], base_prog)
    ctl.ground([("base", [])])

    # Pass 1: prove the balance optimum (bounded so it can never hang).
    symbols, cost, exhausted = _solve_bounded(ctl, balance_time_limit)
    if symbols is None:
        raise RuntimeError("no feasible schedule (hard feed-everyone unsatisfiable)")

    # Ground Pass-2 objectives; lock balance at its proven optimum if we have it.
    ctl.add("opt", [], asp.MIXING_B2B_RULES)
    if exhausted and cost:
        ctl.add("lock", ["cb"], asp.LOCK_PROGRAM)
        ctl.ground([("opt", []), ("lock", [clingo.Number(cost[0])])])
    else:
        ctl.ground([("opt", [])])

    # Pass 2: maximize mixing (>> b2b), best-found within the budget.
    symbols2, _cost2, _exh2 = _solve_bounded(ctl, time_limit)
    if symbols2 is not None:
        symbols = symbols2

    return asp.model_to_schedule(symbols, families)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_solve_optimized.py -v`
Expected: 4 passed. (Each solve is on a tiny instance and finishes in well under the 5s budget.)

- [ ] **Step 5: Commit**

```bash
git add saltshaker/clingo_solver.py tests/test_solve_optimized.py
git commit -m "feat: add one-stage two-pass objectives solver"
```

---

### Task 5: Example objectives tests + synthetic flexible-host fixture

**Files:**
- Create: `tests/test_clingo_objectives.py`
- Modify: `tests/test_balance.py` (add the synthetic end-to-end balance test)

**Interfaces:**
- Consumes: `solve_optimized` (Task 4); `validate`/`measure`; `read_csv`; `examples_dir`/`mkfam`.

**Calibration note:** mixing is best-found within the test budget, so `new_meetings` floors carry generous margin below the 45–60s-measured values (a2 266 / anonymised 271 / example 148). The floors below (a2 ≥ 210, anonymised ≥ 215, example ≥ 110) are ~0.9× the baseline *min* — clingo clears them easily even at a short budget. If a slower CI machine dips under, lower the floor (do not raise the budget into a slow suite).

- [ ] **Step 1: Write the tests**

```python
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
```

Add to `tests/test_balance.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they pass**

Run: `uv run pytest tests/test_clingo_objectives.py tests/test_balance.py -v`
Expected: all pass. a2 balance ≈ 0.10 (≤ 0.15); each example feeds everyone, honors the cap, and beats its `new_meetings` floor; `example_in` uses ≤ 34 dinners. Solves finish within the 8s budget. (If a `new_meetings` floor fails on a slow machine, lower that floor per the calibration note — do not increase the budget.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_clingo_objectives.py tests/test_balance.py
git commit -m "test: add example objectives tests and synthetic balance fixture"
```

---

### Task 6: Wire the CLI to the objectives solver

**Files:**
- Modify: `saltshaker/cli.py`
- Test: `tests/test_cli_objectives.py`

**Interfaces:**
- Consumes: `solve_optimized` (Task 4); `read_csv`/`write_csv`; `measure`.
- Produces: `main(argv=None) -> int` now runs `solve_optimized` with a `--time-limit` (seconds, default 60) and prints balance/mixing in the summary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_objectives.py
from saltshaker.cli import main


def test_cli_runs_objectives_and_writes_outputs(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--seed", "0", "--time-limit", "5"])
    assert rc == 0
    assert out.exists()
    assert (tmp_path / "out.csv.lp").exists()
    lines = out.read_text().splitlines()
    assert lines[0] == "Night,Size,Space,Host,Attendees"
    assert len(lines) > 1
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/test_cli_objectives.py -v`
Expected: FAIL — `--time-limit` is not a recognized argument (argparse error / SystemExit).

- [ ] **Step 3: Modify `saltshaker/cli.py`**

Replace the solver import and call. Change the import line `from saltshaker import clingo_solver` (unchanged) and update `main`:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Schedule saltshaker dinners with clingo (objectives)")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("-s", "--max-dinner-size", type=int, default=8,
                        help="cap every host's seating capacity (default 8)")
    parser.add_argument("--seed", type=int, default=0, help="clingo seed (reproducibility)")
    parser.add_argument("--time-limit", type=int, default=60,
                        help="seconds for the mixing pass (default 60; balance always proves fast)")
    parser.add_argument("--lp", default=None, help="path for the ASP dump (default: <output>.lp)")
    args = parser.parse_args(argv)

    lp_path = args.lp if args.lp is not None else args.output + ".lp"
    families = read_csv(args.input, args.max_dinner_size)
    schedule = clingo_solver.solve_optimized(
        families, seed=args.seed, time_limit=args.time_limit, lp_path=lp_path)
    write_csv(args.output, schedule)

    m = measure(families, schedule)
    hb = m.host_balance
    dev = "%.4f" % hb["max_deviation"] if hb else "n/a"
    print("meals=%d dinners=%d unfed=%d new_meetings=%d host_balance_maxdev=%s"
          % (m.meals, m.dinners, m.unfed_count, m.new_meetings, dev), file=sys.stderr)
    for email, night in m.unfed:
        print("UNFED: %s night %d" % (email, night), file=sys.stderr)
    return 0
```

(Leave the module docstring/imports; `measure` is already imported in phase-1 `cli.py`.)

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/test_cli_objectives.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the FULL suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: everything passes — phase-1 tests (feasibility `solve`, its bite tests, `test_cli_clingo`) unchanged and green, plus all new objectives tests. (The phase-1 `test_cli_clingo` still passes: it runs `main` on `example_in` without `--time-limit`, so the default 60s mixing budget applies and it completes quickly since `example_in` is small.)

- [ ] **Step 6: Commit**

```bash
git add saltshaker/cli.py tests/test_cli_objectives.py
git commit -m "feat: wire CLI to the objectives solver with --time-limit"
```

---

## Self-review notes

- **Spec coverage:** cap/fair-share/pentab (§5–6) → Task 1; ASP parts + hard-feed + cap + knows + builders (§6) → Task 2; aux `T` + bounded async solve (§5, §7) → Task 3; two-pass cost-lock driver + `.lp` (§5, §7) → Task 4; the 3-example beat-baseline + synthetic fixture (§9–10) → Task 5; CLI + `--time-limit` (§8) → Task 6.
- **The Critical review finding (grounding order)** is encoded in Task 4's `solve_optimized`: `base` grounded first, Pass 1 solved, THEN `opt`/`lock` grounded — mixing is never grounded before the balance proof.
- **Wait-for-exhausted-before-lock** is in Task 4 (`if exhausted and cost:` before locking `cost[0]`).
- **Async-cancel** is in Task 3's `_solve_bounded` (`handle.wait`/`cancel`), used everywhere; no invalid `--time-limit` clingo option.
- **Out of scope (2b):** infeasibility auto-relax + fail-loud, retiring phase-1 `solve()` + its tests, parallel, run-report, input validation.
- **Type consistency:** `compute_cap(families)->int`, `compute_target(...)->int`, `pentab_facts(...)->str`, `base_program/aux_program(...)->str`, `_solve_bounded(...)->(symbols,cost,exhausted)`, `solve_optimized(...)->schedule`, `main(argv)->int`. Schedule shape consistent throughout.
- **Open tuning (safe during execution):** the `time_limit`/`balance_time_limit`/`aux_time_limit` defaults and the `new_meetings` test floors (calibrate down if a slow CI flakes; never up into a slow suite).
