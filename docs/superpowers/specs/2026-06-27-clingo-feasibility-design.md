# Clingo Feasibility Core — Design Spec

**Status:** ready for review
**Date:** 2026-06-27
**Parent:** `2026-06-26-refactor-roadmap.md` (see the 2026-06-27 plan revision in that doc)
**Phase:** clingo stage, phase 1 of 3 (feasibility → objectives → report/validation)

---

## 1. Purpose

Prove that the scheduling problem can be modeled in Answer Set Programming and that **clingo
produces valid, everyone-fed schedules** — retiring the project's single biggest unknown before we
invest in objective tuning or I/O work. This phase swaps the solver's *feasibility* layer to clingo;
it deliberately adds **no optimization objectives** (host balance, guest mixing) — those are phase 2.

The output schedule is the same in-memory shape the Stage-1 harness already consumes
(`list` indexed by night; each a `dict` mapping a host `Family` to a `set` of attendee `Family`,
host included), so the Stage-1 checker/metrics validate clingo's output **unchanged**.

## 2. Scope

**In scope:**
- A `pyproject.toml` that makes `saltshaker` an installable package depending on `clingo==5.8.0`.
- An ASP encoding of the hard constraints **H1–H8** plus a top-priority **minimize-unfed** objective.
- In-process clingo solve; parse the optimal model back into the in-memory schedule.
- Dump the generated `.lp` (facts + rules) to disk for audit.
- A minimal CLI that reads the input CSV, solves with clingo, and writes the output CSV.
- Tests using the Stage-1 harness as the oracle.

**Out of scope (later phases / stages):**
- Host-balance and guest-mixing **objectives** (phase 2) — this phase optimizes *only* unfed.
- Infeasibility **fail-loud + global-cap relaxation** (phase 2) — this phase reports unfed via the
  weak constraint and the metrics, and the example inputs are known feasible (see §4).
- The **run-report** (JSON+Markdown) and **input-CSV validation** (phase 3).
- Splitting `schedule.py` into modules, JSON instance/schedule interchange (deferred to Stage 4).
- Removing the random-restart solver. It stays for now; `schedule.py` keeps providing
  `read_csv`/`Family`. (The random solver's Stage-1 example tests continue to pass; the new clingo
  tests are separate. Retiring the random solver happens in phase 2 once clingo meets quality.)

## 3. Decisions feeding this phase

| # | Decision | Source |
|---|----------|--------|
| Plan reorder | clingo is the **next** stage; the old Stage-2 JSON interchange + module split are **deferred to Stage 4**; input-validation + run-report **fold into the clingo stage** (phase 3). | 2026-06-27 interview |
| Feasibility first | The clingo stage is phased: **feasibility → objectives → report/validation**; this spec is feasibility only. | 2026-06-27 interview |
| Packaging | A **`pyproject.toml`** declares `saltshaker` with `dependencies = ["clingo==5.8.0"]` (pinned) and a `pytest` dev extra; the tool runs via **`uv run`** (this box has no pip; clingo 5.8.0 verified importing in-process via uv). | 2026-06-27 interview |
| In-process + `.lp` dump | Use the in-process `clingo` Python API, **and** dump the generated program to `.lp` for the audit trail. | roadmap D9 |
| Fed-everyone as objective | Model "feed everyone" as a **max-priority weak constraint** (`minimize unfed`), so clingo always returns a schedule and names exactly who/where is unfed. | roadmap D4 / research R5 |
| Clean semantics | clingo targets the **clean** objectives (no scoring-bug reproduction); `knows` is irrelevant to feasibility and is omitted here. | roadmap D13 / 3g |

## 4. Background: the examples are capacity-feasible

A per-night capacity check (demand = Σ size of attending families; supply = Σ `space` of available
hosts) shows **positive slack on every night of all three example inputs** (worst-night slack:
a2 +37, anonymised +31, example +106). So `anonymised_in`'s 11 unfed family-nights under the random
solver are a **solver limitation, not a true shortfall** — clingo should feed everyone.

This yields a strong, falsifiable success criterion: **clingo must reach `unfed_count == 0` on all
three examples.** Caveat: the capacity bound is *necessary, not sufficient* — allergy/repel/host_target
packing could still block fed-everyone on a given input. If clingo cannot reach 0 on an example, it
names exactly who/which night, and that becomes a documented phase-2 infeasibility case (not a phase-1
failure to hide).

## 5. Architecture

New modules in the existing `saltshaker/` package (no `schedule.py` split):

```
pyproject.toml              # NEW: package metadata, clingo==5.8.0 dep, pytest dev extra
saltshaker/
  asp.py                    # build facts + program string; parse a clingo model -> schedule
  clingo_solver.py          # in-process Control/ground/solve; seed; .lp dump
  cli.py                    # `python -m saltshaker.cli <in.csv> <out.csv> [opts]`
schedule.py                 # unchanged; still provides read_csv + Family (packaged as a top-level module)
```

**Packaging note (sharpened by spec review):** because the module split is deferred,
`schedule.py`'s `read_csv`/`Family` must remain importable when the package is **built**. A naive
flat-layout `pyproject.toml` (just `[project]` + a backend, no explicit module list) builds a wheel
that contains `saltshaker/` but **silently omits top-level `schedule.py`** — so `saltshaker.cli`'s
`from schedule import read_csv` breaks for any non-cwd use, even though `uv run pytest` stays green
(because `pytest.ini`'s `pythonpath = .` masks the omission at test time). The build config must
**explicitly declare both** the `saltshaker` package and the top-level `schedule` module
(setuptools `[tool.setuptools] py-modules = ["schedule"]` + `packages = ["saltshaker"]`, or
hatchling `include = ["schedule.py", "saltshaker/"]`), and the plan must include a **build/install
verification** that imports `schedule` from *outside* the repo root so the omission cannot hide
behind `pythonpath`. The backend's auto-discovery must also not try to package `tools/` or `tests/`.

**Data flow:** `read_csv` → `families` → `asp.build_program(families)` → clingo solve →
`asp.read_model(symbols, families)` → in-memory `schedule` → existing `write_csv`. The `.lp` text is
written to disk as a side artifact.

## 6. The ASP encoding

Emails and tokens are emitted as **double-quoted string constants** (they contain `@`/`.`).

### 6.1 Facts (emitted per family / per night)
```
night(0..N-1).
family("e").                 % every family
size("e", S).                % every family
space("e", Sp).              % every family (used only when "e" is a host)
canhost("e", Nn).            % per (family, night) where host_nights[Nn] is true
canattend("e", Nn).          % per (family, night) where attend_nights[Nn] is true
htarget("e", T).             % only when host_target is set
allergy("e", "tok").         % one per allergy token
allergen("e", "tok").        % one per allergen token
repel("e", "tok").           % one per repel token
% knows/* intentionally omitted — it only affects the mixing objective (phase 2).
```

### 6.2 Decisions and the static program
```
% choose hosts among those who can host that night (H4 falls out of the canhost domain)
{ host(F,N) } :- canhost(F,N).

% a host attends their own home (H8)
seat(F,F,N) :- host(F,N).

% each attending non-host family takes at most one seat among that night's homes (H7; H5 from canattend)
{ seat(G,H,N) : host(H,N) } 1 :- canattend(G,N), not host(G,N).

% H3 capacity: total seated size (host included via seat(H,H,N)) must not exceed the host's space.
% The G in the sum tuple key keeps equal sizes distinct (avoids the classic #sum collapse).
:- host(H,N), space(H,Sp), #sum { S,G : seat(G,H,N), size(G,S) } > Sp.

% H1 allergy: a GUEST (not the host) must not be seated where the home's allergens clash.
:- seat(G,H,N), G != H, allergy(G,T), allergen(H,T).

% H2 repels: no two co-seated families share a repel token. A < B grounds each unordered pair once
% and only over token-sharing pairs (keeps grounding small).
:- seat(A,H,N), seat(B,H,N), A < B, repel(A,T), repel(B,T).

% H6 host_target: a family hosts at most its target number of times across all nights.
:- htarget(F,T), #count { N : host(F,N) } > T.

% Fed-everyone: an attending non-host with no seat is "unfed"; minimize at top priority.
unfed(G,N) :- canattend(G,N), not host(G,N), not seat(G,_,N).
:~ unfed(G,N). [1@3, G, N]

#show host/2.
#show seat/3.
```

**Why these map to H1–H8:** H1 allergy (guest-only, host exempt via `G != H`), H2 repels, H3
capacity (persons, host included), H4 host-only-on-can-host (domain of `host/2`), H5 attend
availability (domain of `seat/3`/`host/2`), H6 host_target cap, H7 ≤1 seat/night (cardinality `1`
plus host excluded from the guest rule), H8 host-in-own-home (`seat(F,F,N)`). These are exactly the
invariants the Stage-1 checker enforces, so a correct model passes `validate(...) == []`.

### 6.3 Reading the model back
From the optimal model's shown atoms: for each `host(H,N)` create `schedule[N][fam(H)] = set()`;
for each `seat(G,H,N)` add `fam(G)` to `schedule[N][fam(H)]`. `fam(...)` maps the quoted email
string back to the `Family` object (by email). The result is the standard in-memory schedule.

## 7. Solver behavior

- **In-process** `clingo.Control`; add the program, `ground`, `solve` with optimization enabled;
  take the **optimal** model. Capture the last/best model via an `on_model` callback and confirm
  `result.exhausted` (provably optimal). **Do not** take the first model from `solve(yield_=True)` —
  that is a feasible-but-not-optimal schedule and may leave families unfed. For the examples the
  proven optimum is `unfed = 0`. Pass `--warn=none` in the `Control` arguments to silence benign
  `atom does not occur in any rule head` info lines (emitted for families lacking allergy/repel/
  htarget facts) so they don't interleave with the CLI's stderr summary.
- **Reproducibility:** single solver thread + a fixed seed (configured via `Control` arguments,
  e.g. `Control(["--seed=N", "-t", "1"])`) yields a reproducible model for tests. (Multi-thread is a
  phase-2 performance concern.)
- **`.lp` dump:** always write the exact facts + rules text handed to clingo to `<output>.lp` (or the
  path given by `--lp`), so a human can re-run `clingo <file>.lp` independently. This is the audit trail.
- **Grounding size:** small — seats are O(families × hosts × nights); the only pairwise rule
  (repels) is guarded to token-sharing pairs.

## 8. CLI

```
uv run python -m saltshaker.cli <input.csv> <output.csv> \
    [-s/--max-dinner-size N] [--seed N] [--lp <file.lp>]
```
- Reads the input CSV (existing `read_csv`, `-s` clamp as today), solves, writes the output CSV
  (existing `write_csv`), and dumps the `.lp`.
- On success prints a one-line summary to stderr (meals served, unfed count). If `unfed_count > 0`,
  it prints the unfed `(email, night)` list to stderr (phase 1 reports; phase 2 adds the fail-loud
  exit + global-cap relaxation).

## 9. Testing (Stage-1 harness as the oracle)

Run via `uv run pytest` (clingo + pytest both come from the pyproject env).

- **`tests/test_clingo_feasibility.py`** — for each of `a2_in.csv`, `anonymised_in.csv`,
  `example_in.csv`: solve with a fixed seed; assert **`validate(families, schedule) == []`** (H1–H8)
  and **`measure(...).unfed_count == 0`** (everyone fed). Reproducible under the seed.
- **`tests/test_asp.py`** — unit tests on `asp.py` with tiny hand-built `Family` instances solved
  through clingo, asserting each rule bites. **Fixture caution:** `canhost ⊆ canattend` is not
  asserted in ASP (it relies on `read_csv`'s `Can Host ⇒ Can Attend` invariant), so any hand-built
  `Family` that sets a host night MUST also set the matching attend night — otherwise the checker's
  H5 fires on the host and confuses the test.
  - an allergy clash forces the allergic guest into a different home than the clashing host;
  - a repel pair is never co-seated;
  - capacity smaller than the group forces a second host / leaves the model seating within `space`;
  - `host_target = 1` caps a family to one hosting night;
  - a model on a trivially feasible instance reaches `unfed = 0`.
- The model-reading path is covered by asserting the reconstructed schedule has the expected hosts
  and attendee sets on a tiny instance.

## 10. Success criteria (phase-1 exit)

- [ ] `pyproject.toml` builds; `uv run python -m saltshaker.cli ...` solves and writes a CSV.
- [ ] clingo reaches **`unfed_count == 0`** on all three example inputs.
- [ ] `validate(...) == []` (H1–H8) on all three clingo outputs.
- [ ] Reproducible model under a fixed seed (single thread).
- [ ] `.lp` dump written and independently re-runnable with the `clingo` binary.
- [ ] `asp.py` unit tests pin each hard-constraint rule.
- [ ] Stage-1 tests (random solver) still pass; clingo tests run via `uv run pytest`.
- [ ] **Package build verified:** the wheel includes top-level `schedule.py` — confirmed by
      importing `schedule` from *outside* the repo root (not via `pytest`'s `pythonpath`).

> **Pre-verified:** the §6 encoding was transcribed verbatim and run through clingo 5.8.0 + the
> Stage-1 `validate`/`measure` oracles during spec review — SAT with proven optimum `unfed = 0` and
> zero violations on all three examples (anonymised: 219 meals / 63 dinners; a2: 219/65; example:
> 120/42), grounding+solve under 0.1s. Adversarial micro-tests confirmed H1/H2/H3/H6 each enforce.

## 11. Risks & open questions (for the implementation plan)

- **Build backend / packaging top-level `schedule.py`:** the plan picks setuptools vs hatchling and
  the include rule that keeps `schedule.py` importable. Verify `uv run pytest` resolves both
  `import schedule` and `import saltshaker.*` plus `import clingo`.
- **`Control` seed/thread API specifics:** exact arguments for single-thread + seed and for reading
  the optimal model (`solve` with `on_model`, or the last model from the handle) — pin in the plan.
- **Necessary-not-sufficient feasibility:** if an example can't reach `unfed = 0` under
  allergy/repel/host_target packing, capture who/which-night as a documented phase-2 case rather
  than weakening the test.
- **Optimization vs first-model:** the encoding optimizes (minimize unfed); confirm we read the
  *optimal* model, not the first feasible one, so `unfed = 0` is actually achieved when reachable.
