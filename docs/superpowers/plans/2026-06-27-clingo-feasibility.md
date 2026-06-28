# Clingo Feasibility Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the solver's *feasibility* layer with clingo — produce valid, everyone-fed schedules (no optimization objectives yet), validated by the Stage-1 harness.

**Architecture:** A new `pyproject.toml` makes `saltshaker` an installable package depending on `clingo==5.8.0`. `saltshaker/asp.py` emits ASP facts + the static rule program (hard constraints H1–H8 + minimize-unfed) and parses a clingo model back into the in-memory schedule. `saltshaker/clingo_solver.py` solves in-process (seeded, single-thread) and dumps the `.lp`. `saltshaker/cli.py` wires CSV→solve→CSV. `schedule.py` is unchanged (still provides `read_csv`/`Family`).

**Tech Stack:** Python 3, `clingo==5.8.0` (in-process Python API), `pytest` (dev). Everything runs via `uv run` (no pip on this box).

## Global Constraints

- **Dependencies:** `clingo==5.8.0` (pinned, runtime) + `pytest>=7` (dev). Run tests with **`uv run pytest`** and the tool with **`uv run python -m saltshaker.cli ...`**.
- **Do NOT modify** `schedule.py`, `saltshaker/{constraints,metrics,schedule_io,validate_cli}.py`, or any existing Stage-1 test. (The only edit to an existing file is the README test-command line in Task 1.)
- **Emails and allergy/allergen/repel tokens are emitted as double-quoted ASP string constants** (they contain `@`/`.`).
- **Read the OPTIMAL model**, not the first feasible one: capture the last model via an `on_model` callback. (The empty schedule — no hosts, everyone unfed — is always a feasible model, so the program is always SAT; clingo minimizes unfed from there. For the examples the proven optimum is `unfed = 0`.)
- **`clingo.Control` arguments:** `["--warn=none", "--seed=%d" % seed, "-t", "1"]` — `--warn=none` silences benign `atom does not occur in any rule head` info; `-t 1` (single thread) + seed = reproducible.
- **Schedule shape:** `list` indexed by 0-based night; each a `dict` mapping a host `Family` to a `set` of attendee `Family` (host included). `Family` identity is its email.
- **Packaging:** the build must include BOTH the `saltshaker` package AND top-level `schedule.py` (`[tool.setuptools] py-modules = ["schedule"]`, `packages = ["saltshaker"]`); verify the built wheel contains `schedule.py` (a green `uv run pytest` does NOT prove this — `pytest.ini`'s `pythonpath = .` masks the omission).
- **Do not "fix" original spellings** (`summery`, `repel`, etc.).
- Spec: `docs/superpowers/specs/2026-06-27-clingo-feasibility-design.md` (ASP encoding §6).

---

### Task 1: Package the project (pyproject.toml + clingo dependency)

**Files:**
- Create: `pyproject.toml`
- Modify: `README.md` (test-command line only)
- Verify: existing suite via `uv run pytest`; wheel contents via `uv build`

**Interfaces:**
- Produces: a `uv`-resolvable project so `uv run pytest` and `uv run python -m saltshaker.cli` have `clingo` + `pytest` available, and the built wheel includes top-level `schedule.py`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "saltshaker"
version = "0.1.0"
description = "Progressive dinner scheduler"
requires-python = ">=3.9"
dependencies = ["clingo==5.8.0"]

[tool.setuptools]
py-modules = ["schedule"]
packages = ["saltshaker"]

[dependency-groups]
dev = ["pytest>=7"]
```

- [ ] **Step 2: Verify the existing suite still passes under the new run command**

Run: `uv run pytest -q`
Expected: the Stage-1 suite passes (31 passed). `uv` builds/installs the project (with `clingo`) and the `dev` group (`pytest`) automatically. (`import schedule`/`import saltshaker.*` still resolve via `pytest.ini`'s `pythonpath = .`.)
Fallback: if `uv run pytest` reports `pytest` not found, the `[dependency-groups]` table isn't being auto-installed — replace it with `[tool.uv]\ndev-dependencies = ["pytest>=7"]` and re-run. If `import clingo` fails, confirm `dependencies = ["clingo==5.8.0"]` is under `[project]`.

- [ ] **Step 3: Verify the built wheel includes top-level `schedule.py`**

Run: `uv build && python3 -c "import zipfile,glob; w=sorted(glob.glob('dist/saltshaker-*.whl'))[-1]; names=zipfile.ZipFile(w).namelist(); print('schedule.py' in names, [n for n in names if n.endswith('.py') and '/' not in n], [n for n in names if n.startswith('saltshaker/')][:3])"`
Expected: prints `True [...'schedule.py'...] ['saltshaker/__init__.py', ...]` — i.e. the wheel contains `schedule.py` and the `saltshaker/` package. If it prints `False`, the `py-modules` line is missing or wrong — fix before continuing. (Clean up: `rm -rf dist build *.egg-info` after, and ensure they're git-ignored or not staged.)

- [ ] **Step 4: Update the README test command**

In `README.md`, change the test line from `uv run --with pytest pytest` to:

```markdown
    uv run pytest
```

(The `pytest` and `clingo` deps now come from `pyproject.toml`.)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md
git commit -m "build: add pyproject packaging with pinned clingo dependency"
```

(Do not commit `dist/`, `build/`, or `*.egg-info/` — remove them or add to `.gitignore` if they appear.)

---

### Task 2: ASP program builder + model parser (`asp.py`)

**Files:**
- Create: `saltshaker/asp.py`
- Test: `tests/test_asp.py`

**Interfaces:**
- Consumes: `Family` (from `schedule`); `mkfam` (from `tests._support`) in tests; `clingo` directly in tests.
- Produces:
  - `build_facts(families) -> str` — the per-instance ASP facts.
  - `build_program(families) -> str` — facts + the static rules.
  - `model_to_schedule(symbols, families) -> schedule` — reconstruct the in-memory schedule from a model's shown `host/2` and `seat/3` symbols.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_asp.py
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_asp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.asp'`.

- [ ] **Step 3: Implement `saltshaker/asp.py`**

```python
"""Build the ASP program for the feasibility solver and parse clingo models back
into the in-memory schedule.

Emails and allergy/allergen/repel tokens are emitted as double-quoted ASP string
constants. The static rules encode hard constraints H1-H8 plus a top-priority
minimize-unfed objective (see 2026-06-27-clingo-feasibility-design.md, section 6).
"""

# Static ASP rules (everything that is not per-instance facts). See spec 6.2.
RULES = """
{ host(F,N) } :- canhost(F,N).
seat(F,F,N) :- host(F,N).
{ seat(G,H,N) : host(H,N) } 1 :- canattend(G,N), not host(G,N).

:- host(H,N), space(H,Sp), #sum { S,G : seat(G,H,N), size(G,S) } > Sp.
:- seat(G,H,N), G != H, allergy(G,T), allergen(H,T).
:- seat(A,H,N), seat(B,H,N), A < B, repel(A,T), repel(B,T).
:- htarget(F,T), #count { N : host(F,N) } > T.

unfed(G,N) :- canattend(G,N), not host(G,N), not seat(G,_,N).
:~ unfed(G,N). [1@3, G, N]

#show host/2.
#show seat/3.
"""


def _q(s):
    """Quote a string as an ASP double-quoted constant (emails/tokens contain @ and .)."""
    return '"%s"' % s


def build_facts(families):
    """Return the ASP facts (one per line) for a list of Family objects."""
    nights = len(families[0].attend_nights)
    lines = ["night(0..%d)." % (nights - 1)]
    for f in families:
        e = _q(f.email)
        lines.append("family(%s)." % e)
        lines.append("size(%s,%d)." % (e, f.size))
        lines.append("space(%s,%d)." % (e, f.space))
        if f.host_target is not None:
            lines.append("htarget(%s,%d)." % (e, f.host_target))
        for n in range(nights):
            if f.host_nights[n]:
                lines.append("canhost(%s,%d)." % (e, n))
            if f.attend_nights[n]:
                lines.append("canattend(%s,%d)." % (e, n))
        for t in f.allergies:
            lines.append("allergy(%s,%s)." % (e, _q(t)))
        for t in f.allergens:
            lines.append("allergen(%s,%s)." % (e, _q(t)))
        for t in f.repel:
            lines.append("repel(%s,%s)." % (e, _q(t)))
    return "\n".join(lines) + "\n"


def build_program(families):
    """Return the full ASP program (facts + static rules) for the families."""
    return build_facts(families) + RULES


def model_to_schedule(symbols, families):
    """Reconstruct the in-memory schedule from a model's shown host/2 and seat/3 symbols.

    Returns a list indexed by night; each entry a dict mapping a host Family to a
    set of attendee Family objects (host included).
    """
    by_email = {f.email: f for f in families}
    nights = len(families[0].attend_nights)
    schedule = [{} for _ in range(nights)]
    for sym in symbols:
        if sym.name == "host" and len(sym.arguments) == 2:
            host = by_email[sym.arguments[0].string]
            night = sym.arguments[1].number
            schedule[night].setdefault(host, set())
    for sym in symbols:
        if sym.name == "seat" and len(sym.arguments) == 3:
            guest = by_email[sym.arguments[0].string]
            host = by_email[sym.arguments[1].string]
            night = sym.arguments[2].number
            schedule[night].setdefault(host, set()).add(guest)
    return schedule
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_asp.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add saltshaker/asp.py tests/test_asp.py
git commit -m "feat: add ASP program builder and model parser"
```

---

### Task 3: In-process clingo solver (`clingo_solver.py`)

**Files:**
- Create: `saltshaker/clingo_solver.py`
- Test: `tests/test_clingo_solver.py`
- Test: `tests/test_clingo_feasibility.py`

**Interfaces:**
- Consumes: `asp.build_program`/`model_to_schedule` (Task 2); `read_csv` (from `schedule`); `validate` (constraints), `measure` (metrics); `mkfam`, `examples_dir` fixture (tests).
- Produces: `solve(families, seed=0, lp_path=None) -> schedule` — solve the feasibility model and return the optimal in-memory schedule; if `lp_path` is given, write the exact ASP program there.

- [ ] **Step 1: Write the failing tests (per-rule "bite" tests + the 3-example feasibility tests)**

```python
# tests/test_clingo_solver.py
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
```

```python
# tests/test_clingo_feasibility.py
import pytest

from schedule import read_csv
from saltshaker.clingo_solver import solve
from saltshaker.constraints import validate
from saltshaker.metrics import measure

EXAMPLES = ["a2_in.csv", "anonymised_in.csv", "example_in.csv"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_clingo_feeds_everyone_and_is_valid(name, examples_dir):
    families = read_csv(str(examples_dir / name), 8)
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == [], \
        "%s: %s" % (name, [v.message for v in validate(families, schedule)])
    assert measure(families, schedule).unfed_count == 0, "%s left families unfed" % name
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_clingo_solver.py tests/test_clingo_feasibility.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.clingo_solver'`.

- [ ] **Step 3: Implement `saltshaker/clingo_solver.py`**

```python
"""In-process clingo feasibility solver: produce a valid, everyone-fed schedule.

Optimizes only minimize-unfed (no host-balance / mixing objectives yet — that is
phase 2). Single-threaded + seeded for reproducibility; dumps the exact ASP program
to a .lp file for audit. See 2026-06-27-clingo-feasibility-design.md.
"""
import clingo

from saltshaker import asp


def solve(families, seed=0, lp_path=None):
    """Solve the feasibility model for `families` and return the optimal schedule.

    Returns the in-memory schedule (list[dict[Family, set[Family]]]) reconstructed
    from the optimal model. If `lp_path` is given, the exact ASP program (facts +
    rules) is written there for audit.
    """
    program = asp.build_program(families)
    if lp_path is not None:
        with open(lp_path, "w") as fh:
            fh.write(program)

    ctl = clingo.Control(["--warn=none", "--seed=%d" % seed, "-t", "1"])
    ctl.add("base", [], program)
    ctl.ground([("base", [])])

    captured = {"symbols": None}

    def on_model(model):
        # optimization calls this for each improving model; keep the last (best/optimal)
        captured["symbols"] = model.symbols(shown=True)

    ctl.solve(on_model=on_model)
    if captured["symbols"] is None:
        raise RuntimeError("clingo found no model (hard constraints unsatisfiable)")

    return asp.model_to_schedule(captured["symbols"], families)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_clingo_solver.py tests/test_clingo_feasibility.py -v`
Expected: all pass — 7 in `test_clingo_solver.py`, 3 in `test_clingo_feasibility.py`. The three example inputs each solve to `unfed_count == 0` with zero violations (anonymised, which the random solver left with 11 unfed, now feeds everyone).

- [ ] **Step 5: Commit**

```bash
git add saltshaker/clingo_solver.py tests/test_clingo_solver.py tests/test_clingo_feasibility.py
git commit -m "feat: add in-process clingo feasibility solver"
```

---

### Task 4: CLI (`cli.py`)

**Files:**
- Create: `saltshaker/cli.py`
- Test: `tests/test_cli_clingo.py`

**Interfaces:**
- Consumes: `read_csv`/`write_csv` (from `schedule`); `clingo_solver.solve` (Task 3); `measure` (metrics).
- Produces: `main(argv=None) -> int` — read input CSV, solve, write output CSV, dump `.lp`, print a one-line summary. Runnable as `python -m saltshaker.cli <in.csv> <out.csv> [opts]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_clingo.py
from saltshaker.cli import main


def test_cli_writes_output_and_lp(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--seed", "0"])
    assert rc == 0
    assert out.exists()
    assert (tmp_path / "out.csv.lp").exists()           # .lp dumped next to output by default
    lines = out.read_text().splitlines()
    assert lines[0] == "Night,Size,Space,Host,Attendees"
    assert len(lines) > 1                                 # at least one dinner row


def test_cli_custom_lp_path(tmp_path, examples_dir):
    out = tmp_path / "out.csv"
    lp = tmp_path / "audit.lp"
    rc = main([str(examples_dir / "example_in.csv"), str(out), "--lp", str(lp)])
    assert rc == 0
    assert lp.exists()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/test_cli_clingo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'saltshaker.cli'`.

- [ ] **Step 3: Implement `saltshaker/cli.py`**

```python
"""CLI for the clingo feasibility solver:

    uv run python -m saltshaker.cli <input.csv> <output.csv> [-s N] [--seed N] [--lp PATH]

Reads the input CSV, solves the feasibility model with clingo, writes the output CSV,
and dumps the ASP program to <output>.lp (or --lp PATH). Prints a one-line summary
(and any unfed families) to stderr.
"""
import argparse
import sys

from schedule import read_csv, write_csv
from saltshaker import clingo_solver
from saltshaker.metrics import measure


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Schedule saltshaker dinners with clingo (feasibility core)")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("-s", "--max-dinner-size", type=int, default=8,
                        help="cap every host's seating capacity (default 8)")
    parser.add_argument("--seed", type=int, default=0, help="clingo seed (reproducibility)")
    parser.add_argument("--lp", default=None,
                        help="path for the ASP dump (default: <output>.lp)")
    args = parser.parse_args(argv)

    lp_path = args.lp if args.lp is not None else args.output + ".lp"
    families = read_csv(args.input, args.max_dinner_size)
    schedule = clingo_solver.solve(families, seed=args.seed, lp_path=lp_path)
    write_csv(args.output, schedule)

    m = measure(families, schedule)
    print("meals=%d dinners=%d unfed=%d" % (m.meals, m.dinners, m.unfed_count),
          file=sys.stderr)
    for email, night in m.unfed:
        print("UNFED: %s night %d" % (email, night), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/test_cli_clingo.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the FULL suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: all pass — the Stage-1 suite (31) plus the new clingo tests. No existing test changed behavior.

- [ ] **Step 6: Commit**

```bash
git add saltshaker/cli.py tests/test_cli_clingo.py
git commit -m "feat: add clingo feasibility CLI"
```

---

## Self-review notes

- **Spec coverage:** pyproject/packaging + build verification → Task 1; ASP encoding §6 (facts, rules, model parse) → Task 2; in-process solve + seed + `.lp` dump + optimal model → Task 3; the 3-example `unfed==0`/`validate==[]` success criterion → Task 3 (`test_clingo_feasibility.py`); per-rule bite tests → Task 3; CLI §8 → Task 4. The `--warn=none`/optimal-model/`A<B` details are in the Global Constraints + the code.
- **Out of scope (not in this plan):** host-balance/mixing objectives, infeasibility fail-loud + global-cap relaxation, run-report, input-CSV validation, schedule.py module split, retiring the random solver. (Later phases/stages.)
- **Type consistency:** `build_facts/build_program(families) -> str`, `model_to_schedule(symbols, families) -> schedule`, `solve(families, seed=0, lp_path=None) -> schedule`, `main(argv=None) -> int`. `measure(...).unfed` entries are `[email, night]` lists (matched in the tests). Schedule shape is consistent across tasks.
- **Verification reality:** the encoding in Task 2/3 is the spec's §6 verbatim, already run through clingo 5.8.0 + the Stage-1 oracle on all three examples (proven optimum `unfed=0`, zero violations) during spec review — so Task 3's example tests are expected to pass on first green.
- **Open tuning (safe during execution):** the `--seed` default (0) and the build backend (setuptools chosen; hatchling is an equivalent alternative if `uv build` misbehaves — keep `py-modules`/`packages` equivalents).
