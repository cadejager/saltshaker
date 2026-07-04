# Saltshaker Refactor Roadmap

**Status:** approved shape, not yet implemented
**Date:** 2026-06-26
**Owners:** Chris (maintainer), Claude

This is the top-level roadmap for a major refactor of `schedule.py`. It is intentionally
agile: each **stage** is an independently shippable increment with its own exit criteria,
and stages 2–4 each get their own brainstorm → spec → plan cycle when we reach them. Only
Stage 1 is fully specified now (see `2026-06-26-stage-1-test-harness-design.md`).

---

## 1. Goals

1. **Make the scheduler trustworthy to change.** Today there is no test suite; correctness
   is judged by eye and by pasting `INFO` logs into text files. We want an automated safety
   net before we touch the core logic.
2. **Replace the hand-rolled random-restart search with clingo / Answer Set Programming.**
   The hard constraints (allergies, repels, capacity, availability) are a natural fit for ASP.
3. **Redesign input/output** so data is human-auditable at the edges (CSV) and cleanly
   structured between stages (JSON), and so each run emits a durable, comparable result report
   instead of scraped log output.
4. **Eventually automate the whole flow** — ingest Google Forms exports, schedule, and emit a
   per-family PDF — with each step independently runnable and human-auditable.

## 2. Guiding principles

- **Test-first / safety net first.** Nothing in the core logic changes until invariants and a
  quality baseline are captured (Stage 1).
- **Riskiest change last, against stable contracts.** The clingo rewrite (Stage 3) lands only
  after the I/O contracts (Stage 2) are defined, tested, and frozen.
- **Every inter-stage artifact is human-auditable.** A person must be able to open and reason
  about what passed between any two stages. CSV at the human edges; pretty-printed JSON between
  stages; even the clingo program/facts are dumped to `.lp` for inspection.
- **Each stage is independently runnable.** Stages communicate through files, not just
  in-memory calls, so any stage can be run and audited in isolation.
- **Behavior changes are deliberate and measured.** Quality is tracked with a metrics harness
  so we can tell whether any change helps or hurts the soft objectives.

## 3. Decisions log (from the 2026-06-26 interview)

| # | Decision | Rationale / notes |
|---|----------|-------------------|
| D1 | Tests assert **hard-constraint invariants** on every run, **and** track **soft quality metrics** for regression. | Invariants are solver-independent and survive the clingo rewrite; metrics tell us if a change helped or hurt. |
| D2 | **"Everyone fed every night" is a HARD constraint** in the final system. | Today it is only *reported* (`find_starved_family`), never prevented. This is a real semantic change. |
| D2a | But it cannot be a passing invariant in Stages 1–2 (current solver doesn't enforce it). It is a **tracked metric** in Stages 1–2 and is **promoted to a hard invariant in Stage 3**. | Keeps the test suite honest at every stage. |
| D3 | Core scheduling moves to **clingo**, owning **both feasibility and optimization** (ASP weak constraints / priority levels). | Confirmed viable by research, with the caveat in R1 below. |
| D4 | Infeasible inputs → **fail loudly with a who/which-night diagnostic.** The *only* relaxable lever is the **global `-s` per-night dinner-size cap**; an individual host's own `space` is never exceeded. | "Fed everyone" is modeled as a max-priority ASP objective so clingo always returns a schedule and names exactly who is unfed; Python then fails loudly unless relaxing the global cap fixes it. |
| D5 | **CSV at the edges, JSON between stages.** Harden the CSV reader to use **named headers + validation** (kill positional-column fragility) but keep it CSV. | Humans edit/read CSV; stages exchange pretty-printed JSON. |
| D6 | Run result emitted as **structured JSON metrics + a human-readable Markdown summary**, alongside the output CSV. | Replaces pasting `INFO` logs into a text file; JSON enables automated run-to-run comparison. |
| D7 | Sequencing: **Stage 1 (tests) → Stage 2 (I/O) → Stage 3 (clingo) → Stage 4 (automation).** | Big risky change lands last against tested, stable contracts. |
| D8 | Testing uses **pytest** (dev-only dependency). **Adding `--seed` is deferred to Stage 3 (clingo)** — we do not change the current solver's core before a test suite exists, and a fixed seed set is only meaningful once clingo gives reproducible optimization. Stage-1 tests instead run **many trials** and assert invariants on every run. | Runtime stays clean; reproducibility-by-seed lands with clingo. |
| D11 | Stage-1 modules **import `Family`/`read_csv` from `schedule.py`** rather than introducing a shared core now. | Don't move/restructure the core before the test suite exists; the real module split happens in Stage 2. |
| D12 | **Patch the `ZeroDivisionError` in `score_host`/`host_summery` as the first Stage-1 task** (empty flexible-host ratio set → zero penalty). A sanctioned, minimal exception to "don't touch the core." | Verified bug: the solver crashes on any input where *every* family has a `host_target` (incl. `anonymised_in.csv`, `example_in.csv`). Without the patch, two of three example inputs can't produce a schedule or baseline. Chris chose "patch now, test after." |
| D13 | **Metrics measure clean real-world semantics; they do NOT mirror the scoring functions.** The scoring bugs (self-meeting, double-counted pairs, person-vs-seat unit mix) are recorded as known issues for clingo to get right in Stage 3. | The old scores aren't numerically portable to clingo anyway (R1); a correct rewrite should not look like a regression against bug-for-bug baselines. |
| D9 | clingo via the **in-process `clingo` Python package**, **but the solver stage also dumps the generated `.lp` program/facts to disk** as an audit artifact. | User chose the pip package over CLI-subprocess; dumping `.lp` recovers the audit trail the CLI approach would have given for free. |
| D10 | Start clingo as **two ASP programs** (host stage, then guest stage), preserving small auditable hand-offs; keep a **single combined lexicographic model as a documented experiment**. | Matches the auditability value; single-model may yield better solutions and can be evaluated later with the Stage-1 metrics harness. |

### Plan revision (2026-06-27)

After Stage 1 shipped, we reconsidered the ordering. Because the Stage-1 harness already gives
clingo a solver-independent safety net, there is little value in refactoring I/O around the
soon-to-be-replaced random solver. **clingo moves up to be the next stage.**

| # | Revised decision | Rationale |
|---|------------------|-----------|
| D14 | **Reorder: clingo is the next stage** (not the old Stage 2). The old Stage-2 work — **JSON instance/schedule interchange and the `schedule.py` module split — is deferred to Stage 4**, where the full Forms→schedule→PDF pipeline actually makes inter-stage files load-bearing. | The "stable contract" clingo needs is the test/metrics harness (done), not JSON files. Designing JSON contracts / splitting the random solver now is throwaway-risk. The "independently runnable stages" goal (D5) was really about the eventual full pipeline (Stage 4). |
| D15 | The two **solver-independent wins fold into the clingo stage**: **input-CSV validation** (positional + strong validation, not named headers — the example headers vary too much) and the **JSON+Markdown run-report** (summary metrics + key lists; full schedule stays in the output CSV). | Both survive the rewrite and help compare clingo runs. D5's "named headers" is superseded: keep positional reading + a validation layer; the canonical contract is the (future) JSON instance, deferred to Stage 4. |
| D16 | The clingo stage is **phased: (1) feasibility core → (2) objectives + hardening → (3) run-report + input validation**, each its own spec→plan→implement cycle. Phase 1 is specified in `2026-06-27-clingo-feasibility-design.md`. | De-risk the biggest unknown (can ASP model this and feed everyone?) in isolation before objective tuning. |
| D17 | **Packaging:** add a **`pyproject.toml`** making `saltshaker` a package with `clingo==5.8.0` pinned and a `pytest` dev extra; run via **`uv run`** (no pip on the dev box; clingo 5.8.0 verified in-process via uv). | Pinned, reproducible, tool-agnostic dependency declaration. |

### Phase-2 decisions (2026-06-29)

Phase 1 (feasibility) shipped and merged. Phase 2 (objectives) is specced in
`2026-06-29-clingo-objectives-design.md` (phase 2a). Key decisions, several discovered by prototyping:

| # | Decision | Rationale |
|---|----------|-----------|
| D18 | **Objective ladder: feed-everyone (hard) ≫ host-balance ≫ general-meets ≫ fuller-dinners ≫ no-back-to-back.** | Chris's priorities. Balance above mixing (reproducing the old solver's emphasis), but unlike the old solver clingo *also* feeds everyone. |
| D19 | ~~Two-stage solve~~ **SUPERSEDED by D23.** (Originally: stage-1 balance → fix hosts → stage-2 mixing. A deeper 2026-07-03 investigation found the two-stage host-fixing actually *hurts* mixing, and that a one-stage model is both cleaner and better.) | — |
| D23 | **ONE-STAGE solve** (one ASP program, one grounding, two optimization passes: prove balance → lock its cost → optimize mixing). Beats the flat model AND the two-stage design on mixing; proves balance optimal. | 2026-07-03 investigation. The blocker was never staging — it was balance-encoding *granularity* (D24). Locking the balance cost (not the hosts) keeps host choice open, giving better mixing (266–271) than fixing hosts (252). |
| D24 | **Coarse** integer fair-share balance penalty (deviation in tenths, small weights) so clingo **proves** the optimum in ~0.3–2s. A finer ratio encoding finds marginally better M4 but is unprovable and re-stalls the solve. | 2026-07-03 investigation. Accept ~0.01–0.02 M4 for provability; balance is then deterministic. |
| D25 | **Hard "wasted-seats" cap** (Chris's idea): per night, total empty seats ≤ (max host space − 1), as a HARD constraint, NOT a minimized objective. Prevents over-hosting; **replaces the empty-seats objective**; as a hard cap it does **not** bias against small hosts (verified). Also accelerates the balance proof, enabling one-stage. | 2026-07-03 interview + investigation. A per-seat objective would push toward big/full hosts and hurt ratio-balance, which matters more. |
| D20 | **`knows` de-prioritized but "general meets" still optimized = metric M5.** `repels` unchanged (hard H2). | Chris doesn't care about `knows` but still wants distinct-meeting variety. Keeping `knows` facts lets the solver optimize exactly what the report measures; the field can be removed later with negligible effect. |
| D21 | **Balance via `ratio-squared` fair-share with a *computed* anchor** (`T` = flexible host-slot demand from an auxiliary min-dinners solve). Default branch-and-bound, single-thread + seed (deterministic); long budgets acceptable but staging is near-instant. | The earlier 0.27 "ceiling" was a wrong fair-share anchor; computing it correctly reaches 0.10 proven-optimal. `usc` gives no model under hard `:- unfed`. |
| D22 | **Phase 2 is split: 2a objectives (this spec) → 2b hardening** (infeasibility auto-relax + fail-loud, retire the random solver, parallel). Infeasibility handling: **auto-relax the global `-s` cap, then report; fail loud only on a true shortfall** (D4). | De-risk the iterative objective tuning in isolation; 2b is mechanical hardening. |

**Note on D7:** the original "Stage 1 → I/O → clingo → automation" sequencing is **superseded by D14**.
Stage references to "Stage 2 (I/O)" and "Stage 3 (clingo)" elsewhere in this document predate the
revision; read them through D14–D16 (clingo next; I/O interchange + module split → Stage 4).

## 4. Key research findings (full detail in `2026-06-26-clingo-research.md`)

- **R1 — Objective translation is lossy (the one real caveat).** clingo optimizes with
  *integer, linear sums at discrete priority levels*. The current Python objectives use
  **exponential** penalties (`2**(52*|Δ|)`, `2**extra_seats`) and diminishing-returns terms
  (`2 - 1/times`). These **cannot be ported exactly.** The idiomatic approximation is
  **lexicographic priority levels** for dominance (fed ≫ host-balance ≫ mixing), **weights**
  for within-level trade-offs, and **pre-grounded lookup-table facts** for nonlinear shapes.
  We preserve the *ordering* of preferred schedules, not the exact scores — acceptable because
  those constants were always hand-tuned. **Consequence:** scores are not numerically comparable
  across the rewrite; the Stage-1 metrics harness is how we compare old vs new.
- **R2 — Set-overlap is ASP's sweet spot.** `allergies ∩ allergens`, `repels ∩ repels`,
  `knows ∩ knows` become shared-variable joins — far cleaner than the current Python set loops.
- **R3 — Capacity sums** use `#sum { S,G : seat(G,H,N), size(G,S) }`; the `G` in the tuple key
  is essential (a classic ASP bug collapses equal sizes otherwise).
- **R4 — Grounding scale** is trivial for seats (~13k atoms at 40×8); the blow-up risk is
  pairwise repel/novelty constraints (~250k) — guard them so only token-sharing pairs ground.
- **R5 — Anytime + parallel + seed.** `--time-limit` plus reading the best model replaces the
  "run T seconds, keep best" loop; `--parallel-mode`/`-t` replaces the multiprocessing portfolio;
  single thread + fixed `--seed` is reproducible (multi-thread optimum value is stable but the
  witnessing schedule may vary).

## 5. Staged roadmap

Each stage lists sub-steps (independently shippable where possible) and an **exit criterion**.

### Stage 0 — (removed)
Reproducibility via `--seed` was originally going to live here; it is **deferred to Stage 3**.
We do not modify `schedule.py`'s core before the Stage-1 test suite exists, and a fixed seed set
only becomes meaningful with clingo's reproducible optimization.

### Stage 1 — Test + metrics harness  *(fully specified separately)*
- **1.0.** **Patch the `ZeroDivisionError`** in `score_host`/`host_summery` (D12) — the one core change Stage 1 makes, so the other two example inputs can run.
- **1a.** Constraint checker: `validate(families, schedule) → [Violation]` (pure, solver-independent).
- **1b.** Metrics module: `measure(families, schedule) → Metrics` (shared by tests and the Stage-2 run-report).
- **1c.** pytest suite: run the current (unseeded) scheduler on the example inputs over **many
  trials**; assert hard invariants on every run; snapshot aggregate quality metrics as a
  regression baseline.
- **1d.** Standalone validator CLI: audit any `input.csv` + `output.csv` pair by hand.
- **Exit:** `pytest` green on all example inputs; invariants enforced; baseline metrics recorded;
  validator CLI usable. No change to scheduling behavior.

### Stage 2 — I/O redesign (your step 3)
- **2a.** Normalized JSON *instance* schema + CSV→instance loader with named-header parsing & validation.
- **2b.** JSON *schedule* schema + schedule→CSV writer (output CSV unchanged for humans).
- **2c.** Run-report: JSON metrics file + Markdown summary (uses the Stage-1 metrics module).
- **2d.** Split `schedule.py` into modules around these contracts — **still using the current solver**,
  so Stage-1 tests stay green and behavior is unchanged.
- **Exit:** pipeline runs CSV→instance(JSON)→schedule(JSON)→CSV; emits JSON+Markdown report;
  Stage-1 invariants still hold; CSV round-trips losslessly.

### Stage 3 — clingo solver (your step 2, the big one)
- **3a.** ASP encoding of the hard constraints; in-process `clingo`; dump `.lp` for audit.
- **3b.** Host-stage ASP program (balance objective).
- **3c.** Guest-stage ASP program (mixing objective + "fed everyone" at max priority).
- **3d.** Infeasibility handling: fail-loud diagnostic; relax only the global `-s` cap (D4).
- **3e.** Wire `--time-limit` / parallel / `--seed` (this is where seeded reproducibility and the
  fixed test-seed set are introduced); retire the random-restart search.
- **3f.** Validate against the Stage-1 harness: invariants hold **and** quality ≥ baseline;
  **promote "fed everyone" to a hard invariant gate here.**
- **3g.** Get the objectives *right* — the ASP encoding must avoid the known scoring bugs the old
  solver had (see the "Known scoring bugs" appendix in the Stage-1 spec): no self-meetings, count
  each unordered pair once, and account empty seats in *persons* not family-count.
- **Exit:** clingo produces schedules that pass all Stage-1 invariants (including fed-everyone),
  meet or beat baseline quality metrics, run within the time budget, and reproduce under a fixed seed.

### Stage 4 — Full automation (low priority, spec'd later)
- **4a.** Google Forms export → cleaned instance (auto-merge allergies/allergens, strip addresses/PII).
- **4b.** Scheduling (Stages above).
- **4c.** Per-family PDF generation.
- **Exit:** TBD when spec'd.

## 6. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| **Exponential→linear objective translation is lossy (R1).** New schedules may differ qualitatively from old. | Stage-1 metrics harness quantifies the difference; we tune priority levels/weights/lookup-tables until quality ≥ baseline before retiring the old solver. |
| **clingo becomes a required dependency**, ending the stdlib-only/no-install property. | Accepted (D9). Pin the clingo version; document install. Stage-1 tooling stays stdlib + pytest only. |
| **Infeasible inputs** under the new hard "fed everyone" rule. | Fail loudly with diagnostics (D4); single relaxation lever (global `-s` cap) is well-defined. |
| **Grounding blow-up** on pairwise constraints (R4). | Guard pairwise rules to token-sharing pairs only; measure grounding size on the largest example. |
| **Scope creep across stages.** | Each stage has its own spec and exit criterion; no stage starts before the prior stage's exit criterion is met. |

## 7. Deferred / open questions (for later specs)

- Exact revised input-CSV column set and validation rules (Stage 2 spec).
- JSON schema details for *instance* and *schedule* (Stage 2 spec).
- Single-combined-model vs two-stage clingo, decided empirically with the metrics harness (Stage 3).
- Forms-export format and PDF template/layout (Stage 4 spec).
