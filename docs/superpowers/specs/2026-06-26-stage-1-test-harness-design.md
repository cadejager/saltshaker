# Stage 1 Design — Test + Metrics Harness

**Status:** ready for review
**Date:** 2026-06-26
**Parent:** `2026-06-26-refactor-roadmap.md`
**Scope:** the safety net we build *before* touching the scheduler. No scheduling behavior changes.

---

## 1. Purpose

Give us an automated way to (a) **prove every schedule the program emits obeys the hard rules**,
and (b) **measure the soft quality** of a schedule so we can tell whether any future change
(especially the clingo rewrite) helps or hurts. This harness is solver-independent on purpose:
it operates on a schedule + the families it was built from, so it works identically for today's
random-restart solver and tomorrow's clingo solver.

## 2. What "correct" means (extracted from the current code)

These are the **hard constraints** the harness enforces. Each cites where today's code already
upholds it, so the checker is a faithful audit of existing behavior.

| ID | Hard constraint | Source in `schedule.py` |
|----|-----------------|--------------------------|
| H1 | **Allergy (guests only):** a *guest* seated in a home shares no token between its `allergies` and the host's `allergens`. The actual enforcement is in `fill_schedule` L419; the generator's L292–333 is host-*selection* capacity planning, **not** this invariant. A host is **not** checked against their own home's allergens (the generator seeds the host into their own home unconditionally), so the checker audits guests-vs-host only. | `fill_schedule` L419 |
| H2 | **Repels:** no two co-seated families share a `repels` token. | `fill_schedule` L424–429 |
| H3 | **Capacity (persons):** for each host/night, `sum(family.size of attendees) ≤ host.space`. Both quantities are in *persons*. | `hosts_tonight[host] = space - size`, decremented by `guest.size` L406/L420/L433 |
| H4 | **Host availability:** a host only hosts on a night where `host_nights[night]` is true. | generator L279 |
| H5 | **Attend availability:** a family is only seated on a night where `attend_nights[night]` is true. | `fill_schedule` L404 |
| H6 | **Host-target = hard upper cap:** a family with a `host_target` hosts **at most** that many times across all nights (no lower-bound guarantee). NB: the `Family` docstring L29 calls it a "soft limit" — that comment is misleading; the generator enforces it as a hard cap (`host_counts < host_target`, L279). | generator L279 |
| H7 | **Single seat per night:** a family appears in at most one home per night. | implicit in fill loop (`break` after seating) |
| H8 | **Host is present in own home:** every host is an attendee of their own dinner; a family hosts at most one home per night. | generator seeds `schedule[night][host] = {host}`; `write_csv` includes host |

> **H7/H8 caveat:** these hold by construction for schedules the *current solver* emits, but the
> validator CLI (1d) audits arbitrary/hand-edited CSVs where they can be violated — so the checker
> enforces them as real invariants, not assumptions.

**Not a hard constraint in Stage 1:** "everyone available is fed every night." The current
solver does **not** guarantee this (`find_starved_family` only *warns*). So in Stage 1 it is a
**tracked metric** (M2 below), not an asserted invariant. The roadmap promotes it to a hard
invariant in Stage 3, where clingo can guarantee it.

## 3. What "good" means — soft quality metrics (clean semantics, per D13)

These are computed and **recorded, not asserted** (except the floors/ceilings in §5b). Per **D13**
they measure *real-world quality* and intentionally **do NOT reproduce the scoring-function bugs**
(see the Known scoring bugs appendix, §9). They are *informed by* `score_host`/`score_guest`/
`summery`/`host_summery` but corrected. The "Inspired by" column points at the related code, not a
behavior contract.

| ID | Metric (clean definition) | Inspired by |
|----|---------------------------|-------------|
| M1 | `meals` — total (family, night) seatings across the series (host counts as a seating). | `summery` L128 |
| M2 | `unfed` — list of (family, night) where the family was available but seated nowhere; plus `unfed_count`. | `find_starved_family` |
| M3 | `host_counts` — times each family hosts. | `summery` L126 |
| M4 | `host_balance` — for each **flexible** host (no `host_target`): ratio = hosts ÷ nights available. Record the average and **each host's absolute deviation from the average** + the **max deviation** (the real "imbalance" signal). No stdev (the objective doesn't use one). Guard the all-targeted case (empty set → report `null`, don't divide by zero). | `host_summery` L169–176 |
| M5 | `new_meetings` — count of **distinct unordered** family-pairs `{A,B}`, `A≠B`, co-seated at least once whose `knows` sets do **not** intersect. **Excludes self-pairs; counts each pair once.** | `score_guest` L255 |
| M6 | `repeat_meetings` — of those distinct pairs, how many were co-seated on >1 night. Computed in the **same single pass** as M5 (no second meets-loop). | `score_guest` L246–247 |
| M7 | `empty_seats` — per host/night `host.space − sum(family.size of attendees)`, in **persons** (not family-count); total and per-dinner distribution. | `score_guest` L235 |
| M8 | `back_to_back_host_incidents` — number of (host, night) cases where the host also hosted the previous night (incidents, matching the per-incident penalty; also record distinct-host count separately). | `score_host` L201 |
| M9 | `dinners` — total number of dinners (host-nights). | `score_host` L195 |

The metrics module is the **single source of truth** reused by the Stage-2 run-report (D6), so we
don't duplicate this logic again (the codebase already duplicates `score_*` vs `*_summery`; we
won't add a fourth copy).

## 4. Architecture

Four small, independently understandable units, plus **one sanctioned bugfix** to the existing
script (the `ZeroDivisionError`, D12 — see §4f).

```
schedule.py            # existing solver — only the D12 crash patch in Stage 1; otherwise unchanged
saltshaker/
  constraints.py       # 1a  validate(families, schedule) -> list[Violation]
  metrics.py           # 1b  measure(families, schedule) -> Metrics
  schedule_io.py       # shared helper: load an output CSV back into the in-memory schedule
  validate_cli.py      # 1d  CLI: audit an (input.csv, output.csv) pair
tests/
  conftest.py          # example-input fixtures, seeded-run helper
  test_constraints.py  # unit tests for the checker (hand-built good/bad schedules)
  test_metrics.py      # unit tests for metric math
  test_examples.py     # 1c  run seeded solver on examples; assert invariants; snapshot baseline
  baselines/           # recorded quality metrics per example input (JSON)
```

> **Note on packaging:** introducing a `saltshaker/` package is the smallest move that lets tests
> import the checker/metrics without copy-pasting from the 600-line script. The existing
> `schedule.py` keeps working as-is; we do **not** rewrite or even modify it in Stage 1. The new
> modules **import `Family` and `read_csv` from `schedule.py`** (decision D11) rather than
> introducing a shared core — the real module split is deferred to Stage 2.

### 4a. Constraint checker — `constraints.py`

- **Input:** `families: list[Family]`, `schedule: list[dict[Family, set[Family]]]` (today's
  in-memory shape — a list indexed by night, each a dict of host → set of attendees).
- **Output:** `list[Violation]`, where `Violation` carries `rule_id` (H1–H8), `night`, the
  families involved, and a human-readable message. **Empty list = valid.**
- **Pure:** no I/O, no logging, no randomness. One function per rule, composed by `validate`.
- Designed to run against *any* schedule regardless of which solver produced it.

### 4b. Metrics module — `metrics.py`

- **Input:** same `(families, schedule)`.
- **Output:** a `Metrics` object/dataclass with fields M1–M9, JSON-serializable.
- **Pure** and deterministic given its inputs.

### 4c. Schedule I/O helper — `schedule_io.py`

- `load_output_csv(input_csv, output_csv) -> (families, schedule)`: reconstructs the in-memory
  schedule from an output CSV (resolving emails back to the families parsed from the input CSV)
  so the checker/metrics can audit a file produced by any past run. Reuses the existing
  `read_csv` for the input side.
- **Reconstruction rules (resolving reviewer B1–B3):**
  - **Night count comes from the input** (`len(attend_nights)`), not the output — nights with
    zero dinners have no rows but must still exist as empty slots in the schedule list.
  - **All input families are retained**, even those absent from the output — `unfed`/M2 needs them.
  - **Host capacity for H3 is read from the output CSV's `Space` column**, not re-derived via
    `read_csv` (which would re-apply whatever `-s`/`max_dinner_size` clamp the validator happens to
    run with and may not match the original run). This keeps audits self-contained. *(Resolves B1.)*
  - **Malformed output is reported, not crashed on:** duplicate `(Night, Host)` rows, an attendee
    email not present in the input, or a host missing from its own attendee list are surfaced as
    violations/warnings — auditing hand-edited CSVs is the CLI's whole purpose. *(Resolves B3.)*

### 4d. Validator CLI — `validate_cli.py`

- Usage: `python -m saltshaker.validate_cli <input.csv> <output.csv> [--metrics]`
- Prints any violations (non-zero exit if any) and, with `--metrics`, prints the quality metrics.
- This is the manual audit tool: point it at any historical run to check it by hand.

### 4e. `schedule.py` is otherwise untouched in Stage 1

Apart from the §4f crash patch, `schedule.py` is **not modified** in Stage 1 — we will not
restructure the solver core before the test suite exists. Reproducibility via `--seed` is
**deferred to Stage 3 (clingo)**, where a fixed seed set first becomes meaningful. Stage 1 treats
the solver as a nondeterministic black box (see §5c).

### 4f. Task 1.0 — patch the `ZeroDivisionError` (D12)

**Do this first**, before building baselines (the other two example inputs can't run otherwise).

- **Bug:** `score_host` (L210) and `host_summery` (L171) compute
  `sum(host_ratios.values()) / len(host_ratios)`. `host_ratios` is built only from *flexible* hosts
  (`host_target is None`, L198). When **every** family has a `host_target` (true for
  `anonymised_in.csv` and `example_in.csv`), that set is empty → division by zero → crash.
- **Verified:** `./schedule.py examples/in/anonymised_in.csv … -t 1` and `…/example_in.csv` both
  raise `ZeroDivisionError`; `a2_in.csv` (34 flexible hosts) runs fine.
- **Fix:** minimal guard — if there are no flexible hosts, the host-ratio balance term contributes
  **zero** (there is nothing to balance), skipping the average/penalty math. Apply the identical
  guard in both `score_host` and `host_summery` (they duplicate the logic — per CLAUDE.md keep them
  consistent). Behavior is unchanged for inputs that already worked (a2 and any mixed input).
- **Sequencing:** Chris chose **patch now, test after** — apply the fix, then build the suite around
  the now-working solver. A regression test covering the all-`host_target` case is part of 1c so the
  crash can't silently return.
- **Note on `example_in.csv`:** it sets `host_target` on families with `space==0` (can't host),
  which is contradictory — that file reads as illustrative/placeholder data. The patch makes it
  *run*; whether it's a meaningful baseline is a separate question for the implementation plan.

## 5. Test design

### 5a. Unit tests (`test_constraints.py`, `test_metrics.py`)
Hand-built tiny schedules with known answers — a clean schedule (zero violations), plus one
schedule that deliberately breaks each of H1–H8, and small fixtures with known metric values.
These don't run the solver; they pin the checker/metrics math directly.

### 5b. Example/integration tests (`test_examples.py`)
For each bundled input (`example_in.csv`, `a2_in.csv`, `anonymised_in.csv`):
1. Run the (unseeded) solver with a short time budget over **N trials** (N small but >1).
2. **Assert `validate(...) == []`** on **every** produced schedule (H1–H8 hold on *every* trial —
   this is the core safety net, and running many trials is what gives it teeth against a
   nondeterministic solver).
3. **Aggregate metrics** across the trials (min/mean/max) and compare to the recorded
   `baselines/<input>.json`:
   - **Floors that should never regress** (e.g. `min(meals)` ≥ recorded floor) are **asserted**.
   - **Ceilings that should never grow** — notably `max(unfed_count)` ≤ recorded ceiling — are also
     **asserted**, so a change that *worsens* starvation fails the build even though "feed everyone"
     isn't yet a hard invariant (D2a). *(Resolves reviewer Q5.)*
   - **Volatile metrics** (mixing, host-balance deviation) are **recorded/compared with tolerance**
     and surfaced on change rather than failing the build — so the baseline tracks drift without
     making the suite flaky.
   - Floors/ceilings are set with a **generous margin** off the observed values (iteration count,
     and thus quality, scales with machine speed — a baseline captured locally must not flake on a
     slower CI box). *(Resolves reviewer Q3.)*

All three example inputs run once Task 1.0 (§4f) lands.

### 5c. Handling nondeterminism
The current solver uses unseeded `random` and we are deliberately **not** adding `--seed` yet
(D8/D11). So Stage 1 treats it as a black box and leans on **volume**: running N trials per input
ensures the hard invariants (H1–H8) hold across many random trajectories, not just one lucky run.
Hard invariants must hold on *all* trials; soft metrics are aggregated (min/mean/max) across
trials for the baseline. (Seeded, exactly-reproducible runs arrive in Stage 3 with clingo.)

### 5d. Baseline regeneration
A documented command (e.g. a small `tools/update_baselines.py` script) regenerates
`baselines/*.json` as aggregate stats over N trials. Baselines are committed so changes to soft
quality show up as reviewable diffs — the durable, comparable replacement for pasting `INFO` logs
into a text file. Because runs are unseeded, baselines store ranges/floors with tolerance, not
exact values.

## 6. Success criteria (Stage 1 exit)

- [ ] Task 1.0 patch applied; all three example inputs run without crashing; a regression test
      covers the all-`host_target` case.
- [ ] `pytest` passes on all three example inputs.
- [ ] Checker enforces H1–H8; unit tests cover a deliberate violation of each.
- [ ] Metrics module computes M1–M9 with **clean semantics** (no self-meetings, dedup'd pairs,
      person-based empty seats); unit tests pin the math.
- [ ] Baseline metrics recorded and committed per example input, with asserted floors (meals) and
      ceilings (unfed_count) carrying a margin, and volatile metrics report-only.
- [ ] Validator CLI audits an arbitrary (input, output) CSV pair, including malformed/hand-edited ones.
- [ ] **`schedule.py` changes are limited to the Task 1.0 crash patch** — no other
      scheduling-behavior change.

## 7. Explicitly out of scope for Stage 1

- No clingo, no ASP (Stage 3).
- No JSON instance/schedule formats, no run-report files, no CSV reader changes (Stage 2).
- No new scheduling logic and no enforcement of "fed everyone" (that's Stage 3).
- No `--seed` / reproducibility work on `schedule.py` (deferred to Stage 3).
- No fixing of the *scoring* bugs in §9 — Stage 1 only avoids reproducing them in the metrics; the
  solver keeps optimizing its current (buggy) objective until clingo replaces it in Stage 3. The
  Task 1.0 patch fixes only the **crash**, not the scoring semantics.
- No spelling fixes to existing identifiers (`summery`, `penility`, etc.) — per CLAUDE.md, match
  existing names to avoid breaking references.

## 8. Open questions for the implementation plan

- **Resolved (D11):** Stage-1 modules **import `Family`/`read_csv` from `schedule.py`**; no shared
  core is introduced until Stage 2.
- **Deferred to Stage 3:** any fixed seed set (seeds are meaningless before clingo).
- Number of trials `N` and per-input time budget for `test_examples.py` — small enough to keep the
  suite fast, large enough to exercise the invariants. (Plan-time tuning; reviewer's rough default
  N≈5–10, `-t 1`, `-p 1`.)
- Tolerance bands for volatile soft metrics in the baseline comparison.
- Whether `example_in.csv` (contradictory `host_target` on non-hosts) is a *meaningful* baseline or
  just a smoke-test that it runs — decide when recording baselines.

## 9. Appendix — Known scoring bugs in `schedule.py` (do NOT reproduce; fix in clingo)

Recorded per **D13**. The metrics module (§3) deliberately does not reproduce these; the Stage-3
clingo encoding must get them right (roadmap step 3g).

1. **Self-meetings.** `score_guest` iterates `for match in attendees` *including the family itself*
   (L246), so every family "meets" itself. Combined with #3, families with empty `knows` score a
   bogus self-bonus.
2. **Double-counted pairs.** Both `(A,B)` and `(B,A)` are counted (L246–247), so every real pair is
   counted twice.
3. **Empty-seats unit mismatch.** `score_guest` uses `extra_seats = host.space − len(attendees)`
   (L230/L235) — seats (persons) minus a *family count*. Capacity (H3) correctly uses
   `sum(size)`. The empty-seats penalty is therefore computed against the wrong quantity.
4. **`knows`-empty edge.** An empty `knows` set never intersects, so families with no `knows`
   always score the novelty bonus — including, via #1, with themselves.

None of these affect the **hard** constraints (H1–H8); they only distort the soft objective. They
are why a faithful "mirror" of the scoring would be a poor regression target (D13).
