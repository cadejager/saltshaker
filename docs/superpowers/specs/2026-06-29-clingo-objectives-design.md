# Clingo Objectives (One-Stage) — Design Spec

**Status:** ready for review
**Date:** 2026-06-29 (revised 2026-07-03 to one-stage)
**Parent:** `2026-06-26-refactor-roadmap.md`; follows `2026-06-27-clingo-feasibility-design.md`
**Phase:** clingo stage, phase 2a of 2 (objectives → hardening). Hardening (infeasibility auto-relax, retire random solver, parallel) is **2b**.

---

## 1. Purpose

Phase 1 made clingo produce *valid, everyone-fed* schedules. Phase 2a makes them **good**: optimize host-balance and guest-mixing so clingo **meets or beats the committed quality baselines**. A focused investigation (§4) settled the architecture: a **single-stage** model — enabled by a hard "wasted-seats" cap — proves host-balance optimal and beats both the flat multi-objective model *and* a two-stage host-fixing design on mixing, while feeding everyone (which the old solver did not).

## 2. Scope

**In scope:**
- A **one-stage solve**: one ASP program, one grounding, solved in two optimization passes (prove balance → lock it → optimize mixing), preceded by a tiny auxiliary min-dinners solve to anchor the balance target.
- A hard **wasted-seats cap** (Chris's constraint): per night, total empty seats ≤ a data-derived cap. This **replaces** an empty-seats objective and prevents over-hosting *without* biasing against small hosts.
- **Coarse** fair-share host-balance encoding (provable), mixing = metric M5, back-to-back as the lowest tie-breaker.
- `--time-limit` (real async time-bounding) and `--seed`; `.lp` dump for audit.
- Tests asserting clean metrics beat baseline, plus a synthetic flexible-host fixture.

**Out of scope (phase 2b / later):**
- Infeasibility **auto-relax of the global `-s` cap + fail-loud** (D4). 2a hard-constrains `:- unfed`; a truly infeasible input is UNSAT and 2a raises — 2b adds graceful relaxation. Example inputs are all feasible.
- **Retiring the random solver** and switching the Stage-1 random-solver tests to clingo (2b). 2a leaves `schedule.py` + existing tests intact and adds *new* clingo-objective tests.
- **Parallel solving** — 2a is single-thread for reproducible balance; 2b may add parallel.
- The **run-report** (JSON+Markdown) and **input-CSV validation** (phase 3).

## 3. Decisions feeding this phase

| # | Decision | Source |
|---|----------|--------|
| Objective ladder | **feed-everyone (hard) ≫ host-balance ≫ general-meets ≫ no-back-to-back.** (Empty-seats is a hard cap, not a ladder level — see below.) | 2026-06-29/07-03 interviews |
| **One stage** | A single ASP program (one grounding, two optimization passes) — **supersedes the earlier two-stage decision (roadmap D19)**. The blocker was never staging; it was balance-encoding granularity. Coarse fair-share is provable and one-stage matches/beats two-stage. | 2026-07-03 investigation |
| **Wasted-seats cap** | Per night, **total empty seats ≤ (max host space − 1)**, as a HARD constraint (not a minimized objective). Prevents over-hosting; replaces any empty-seats objective; as a hard cap it does **not** bias against small hosts (verified). | 2026-07-03 interview + investigation |
| Coarse balance | Host-balance uses a **coarse** integer fair-share penalty (deviation in tenths, small weights) so clingo can **prove** the optimum (~0.3–2s). A finer ratio encoding finds marginally better balance but is unprovable and re-stalls one-stage. Accept ~0.01–0.02 M4 for provability. | 2026-07-03 investigation |
| Mixing = M5 | `knows` de-prioritized but "general meets" still optimized = metric M5. `repels` unchanged (hard H2). Keep emitting `knows` facts so the solver optimizes exactly what the report measures. | 2026-06-29 interview |
| Balance proven, mixing best-found | Host-balance (Chris's top priority) is **proven-optimal and deterministic**. Mixing (and the aux target `T`) are **best-found within a time budget** — like the old solver, which never proved anything. Long budgets OK; balance is near-instant. | 2026-07-03 interview + investigation |
| 2a/2b split | 2a = objectives (this spec); 2b = hardening (infeasibility auto-relax + fail-loud, retire random solver, parallel). | 2026-06-29 interview |

## 4. Investigation evidence (what makes this spec safe to write)

Three prototype rounds ran the encodings through clingo 5.8.0 + the Stage-1 `validate`/`measure` oracles; the 2026-07-03 round settled architecture (single seed, 1 thread):

- **One-stage is viable and best.** Coarse fair-share balance **proves optimal on a2 in 0.35s** (M4 = 0.1036). The recommended driver — one `Control`, one grounding, a cost-lock between two `solve()` calls — gets **a2 mixing 266–271**, beating the two-stage host-fixing design (252) and the old solver's baseline (235–259), because it keeps host choice open. A single `solve()` with `--opt-strategy=bb,hier` is an acceptable simpler alternative (~5–10 fewer meetings).
- **The flat multi-objective model stalls** (a2 balance ~0.23–0.44 in 120s) — lower objectives destabilize the lexicographic B&B. Confirmed and *worse* with empty/b2b added.
- **The wasted-seats cap** (Cap = max host space − 1): kills over-hosting (`example_in` → **30 dinners, 146 meets** vs the uncapped 50-dinner failure and baseline max 131); **does not bias small hosts** (a2 balance 0.097–0.104, equal or better than uncapped); feeds everyone with zero violations on all three; and *accelerates* the balance proof (12–17s → part of why one-stage converges). It **replaces** the empty-seats objective (measured empty seats 11–20 with the cap vs 24–60 when minimizing empties, at better dinner counts).
- **Determinism:** balance is proven (bit-stable across seeds); mixing keeps climbing with budget (a2 250→271 by 60s) and is the natural sink for leftover time.

## 5. Architecture

Extend the existing package (no `schedule.py` split — deferred):

```
saltshaker/
  asp.py            # add: knows facts; the wasted-seats cap; coarse balance (pentab) facts+rules; mixing/b2b; the cost-lock subprogram
  balance.py        # NEW: compute fair-share target T (aux) and the coarse per-host penalty table (pentab)
  clingo_solver.py  # solve() = aux T -> one grounded program -> two-pass cost-lock solve; async time-bound; .lp dump
  cli.py            # add --time-limit; keep --seed/-s/--lp
```

**Pipeline (`clingo_solver.solve`):**
1. **Compute the cap** from the input: `Cap = max(f.space) − 1` over families that can host on ≥1 night (a large-`space` family that never hosts must not inflate the cap).
2. **Aux min-dinners solve** *(only if flexible hosts exist)*, short budget, **best-found**: minimize total dinners under hard-feed + H1–H8 + the cap. From its model, `T = #{host(F,N) : F flexible}` (the flexible host-slot demand).
3. **Build the coarse penalty table** (`balance.py`): for each flexible `F` and each possible count `C ∈ 0..nights`, `P = |10*C − round(10*T*attend(F)/A)|`, `A = Σ_flexible attend`. Emit `pentab("F",C,P).`. (Over-generating rows for counts a host can't reach is harmless — `hostcnt(F,C)` only binds achievable `C`; do **not** "tighten" the range into a bug.)
4. **Ground the base part into one `Control`:** facts + cap + balance (pentab rules + `[P@3]`). **Mixing, b2b, and the lock subprogram are NOT grounded yet** — grounding the `@2` mixing level now prevents Pass 1 from cheaply *proving* the `@3` balance optimum (it stalls at ~0.35, the flat-model failure of §4).
5. **Pass 1** — solve optimizing host-balance to **proven optimum**: wait for `result.exhausted`, then read `cb = model.cost[0]` from the optimal model. If Pass 1 does *not* exhaust within its budget, do **not** lock a non-optimal `cb` (that reproduces the stall).
6. **Ground the second part into the same `Control`:** the `lock(cb)` subprogram `:- #sum{P,F: balpen(F,P)} > cb.` **together with** the mixing and b2b rules.
7. **Pass 2** — solve optimizing mixing ≫ b2b in the remaining budget (**best-found**); reconstruct the final schedule.

If there are **no flexible hosts** (`anonymised`, `example` — all `host_target`): skip the aux + balance layer; the cap alone yields baseline-beating dinner counts. Solve = optimize mixing ≫ b2b under hard-feed + cap.

Output is the same in-memory schedule shape the Stage-1 harness consumes.

## 6. The ASP encodings (verified by the investigation)

Emails/tokens as double-quoted strings, as in phase 1. Phase-1 hard constraints H1–H8 are reused; the feed rule becomes **hard**: `:- unfed(G,N).` replaces phase-1's weak `:~ unfed(G,N). [1@3,...]`.

### 6.1 Wasted-seats cap (HARD)
```
cap(Cap).                                   % Cap = max host space − 1, emitted from Python
:- night(N), cap(Cap),
   #sum { Sp,H : host(H,N), space(H,Sp) ; -S,G : seat(G,H,N), size(G,S) } > Cap.
```
The `#sum` is (total host capacity offered that night) − (total seated that night) = total empty seats that night; the constraint bounds it to `Cap`.

### 6.2 Coarse host-balance (flexible hosts only)
```
flexible(F) :- canhost(F,_), not htarget(F,_).
hostcnt(F,C) :- flexible(F), C = #count { N : host(F,N) }.
balpen(F,P)  :- hostcnt(F,C), pentab(F,C,P).           % pentab emitted from Python (coarse table)
:~ balpen(F,P). [P@3, F]
```
`pentab(F,C,P)`: `P = |10*C − round(10*T*attend(F)/A)|` — the count's absolute deviation (in tenths) from the availability-proportional fair share. Coarse (small weights) ⇒ provable.

### 6.3 Mixing (= metric M5) and back-to-back
```
sharedknows(A,B) :- knows(A,T), knows(B,T), A < B.
meet(A,B) :- seat(A,H,N), seat(B,H,N), A < B, not sharedknows(A,B).
:~ meet(A,B). [-1@2, A, B]                              % maximize distinct new meetings
b2b(F,N) :- host(F,N), host(F,N-1).
:~ b2b(F,N). [1@1, F, N]                                % minimize back-to-back hosting
```

### 6.4 Balance cost-lock (multi-shot)
A parameterized subprogram grounded after Pass 1 with the proven balance cost `cb`:
```
#program lock(cb).
:- #sum { P,F : balpen(F,P) } > cb.
```
Locking balance at its optimum keeps host choice **open** for Pass 2 (better mixing than fixing hosts).

## 7. Solver behavior

- **Recommended driver — one `Control`, grounded in TWO steps, two `solve()` passes.** `Control(["--warn=none", "--seed=%d" % seed, "-t", "1"])`; default branch-and-bound (NOT `usc` — no model under hard `:- unfed`). Ground **base** (facts+cap+balance) → Pass 1 optimizes `@3` balance to proven optimum (`result.exhausted`, ~0.3–2s) and reads `cb`; then ground **lock+mixing+b2b** into the same `Control` → Pass 2 optimizes `@2`≫`@1` (mixing≫b2b) for the remaining budget, taking the best model via `on_model`. **Grounding mixing before Pass 1 breaks the balance proof** (measured: stalls at 0.35) — the two-step grounding is essential to this driver.
- **Simpler alternative — one grounding, one `solve()`:** ground the *whole* program (facts+cap+balance+mixing+b2b) at once and solve with `--opt-strategy=bb,hier`, which proves balance level-by-level then descends to mixing (measured: bal 0.10 proven, mixing 259 — ~5–10 fewer meetings). Valid because `bb,hier` proves each priority level before the next; only this fallback may ground everything up front. The two-pass driver is primary.
- **Time-bounding:** `--time-limit` is **not** a clingo `Control` option — bound Pass 2 (and the aux) with `ctl.solve(async_=True)` + a timer calling `handle.cancel()`. Default budget generous (mixing climbs with time); tests use a short budget.
- **Determinism:** balance is proven ⇒ bit-reproducible under a fixed seed + single thread. Mixing and the aux `T` are best-found within the budget ⇒ wall-clock/machine-sensitive; tests assert floors-with-margin, not exact values.
- **Cap retry — DEFERRED to 2b** (roadmap D26): derive `Cap` from data (`max space − 1`, safe on all three examples). An over-tight cap can fail to return a model *without proving UNSAT*. The probe-and-relax loop is deferred to 2b alongside the global-`-s` auto-relax; **2a ships an honest failure message** distinguishing infeasible (Pass 1 exhausted, no model) from a budget-expired stop, and mentioning cap-too-tight as a cause. No example input exercises this path.
- **`.lp` dump:** write the grounded program (facts + rules) to `<output>.lp` for audit.

## 8. CLI

```
uv run python -m saltshaker.cli <input.csv> <output.csv> [-s N] [--seed N] [--time-limit S] [--lp PATH]
```
Reads input, runs the one-stage solve, writes the output CSV, dumps the `.lp`, and prints a one-line stderr summary (`meals`, `dinners`, `unfed`, `new_meetings`, and a2-style `host_balance` max_deviation when flexible hosts exist). Full reporting is phase 3.

## 9. Testing (Stage-1 harness as oracle)

Run via `uv run pytest`. Balance proves in seconds; the mixing budget in tests is short.

- **`tests/test_clingo_objectives.py`** — for each of `a2_in`, `anonymised_in`, `example_in`: solve; assert `validate(...) == []`, `unfed_count == 0`, and **total empty seats per night ≤ `Cap`**. For `new_meetings`, assert a **floor calibrated from a short-budget run on the test machine with generous margin** — because mixing is best-found and the test budget is short, hardcoding a tight floor near the 60s-measured values (a2 260+/anonymised 273/example 146) would flake on slower machines. The plan calibrates the constants (a conservative starting point: ~0.9× the baseline *min*, i.e. a2 ≳ 210, anonymised ≳ 215, example ≳ 110 — clingo should clear these easily even short-budget, and it beats baseline given time). For `a2` also assert `host_balance["max_deviation"] <= 0.15` (proven ~0.10 — this one is deterministic, so no margin needed beyond the coarse-model wobble). For `example` assert `dinners <= 34` (cap prevents over-hosting; measured 30). Balance reproducible under a fixed seed.
- **`tests/test_balance.py`** — unit tests on `balance.py`: the aux `T` extraction and the coarse `pentab` penalty table math on a hand-built instance; plus a **synthetic many-flexible-host fixture** (more, and varied-availability, flexible hosts than a2's ~22) solved end-to-end, asserting a low `max_deviation` — validating balance on more than a2.
- **`tests/test_asp.py` additions** — the cap constraint, `pentab`/`knows` facts, and the `lock(cb)` subprogram assemble and ground correctly; a tiny instance round-trips.
- Phase-1 feasibility tests continue to pass.

## 10. Success criteria (phase-2a exit)

- [ ] One-stage `solve()` on all three examples: `unfed_count == 0`, `validate(...) == []`, and **total empty seats per night ≤ `Cap`**.
- [ ] **a2 `host_balance` max_deviation ≤ 0.15** (proven; ~0.10), beating the old ~0.17.
- [ ] `new_meetings` clears calibrated floors-with-margin on all three (deterministic-balance run beats baseline given the budget; test floors carry margin for short-budget/slow-machine runs — see §9).
- [ ] `example_in` uses ≤ 34 dinners (no over-hosting).
- [ ] Balance reproducible under a fixed seed; mixing best-found within budget.
- [ ] Synthetic many-flexible-host fixture solves to a low max_deviation.
- [ ] `.lp` dump written and re-runnable; phase-1 + Stage-1 suites still green.

## 11. Risks & open questions (for the implementation plan)

- **Coarse-vs-fine balance:** the plan must use the coarse penalty table (provable). The finer ratio encoding (M4 0.091) is unprovable and re-stalls the solve — do not use it. M4 can wobble ~0.097–0.11 among equally-optimal coarse models (cost is count-deviation, not ratio-max); the ≤0.15 bar carries margin.
- **Cap derivation + retry:** `Cap = max space − 1`. An over-tight cap does **not** fail fast (no quick UNSAT proof) — the plan must probe and relax, and never let the cap starve anyone (feasibility `:- unfed` still dominates; if cap+feed is jointly infeasible, that surfaces as no-model → relax cap).
- **Multi-shot mechanics:** grounding `lock(cb)` in the same `Control` after Pass 1 (clingo multi-shot). The plan pins how `asp.RULES` is split into composable parts (hard core / cap / balance / mixing / b2b / lock) since the feed rule is now hard and there is a parameterized subprogram.
- **`T` is best-found**, not proven (min-dinners doesn't exhaust quickly). A slightly different `T` shifts fair-share a little; the ≤0.15 bar absorbs it.
- **Determinism vs budget:** balance deterministic; mixing wall-clock-sensitive → floors-with-margin tests (mirrors Stage 1).
- **`--time-limit` implementation:** must be async-cancel, not a clingo option (it errors).
