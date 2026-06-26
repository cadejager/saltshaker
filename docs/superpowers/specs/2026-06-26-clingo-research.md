# Reimplementing the Saltshaker dinner scheduler in clingo / ASP

Research notes. Sources are linked at the bottom. ASP = Answer Set Programming;
clingo = grounder (gringo) + solver (clasp).

---

## 1. Modeling the problem in ASP

### Facts (the "instance", ideally an auditable generated `.lp` file)

```prolog
% one fact per family
family(f1). size(f1, 4). space(f1, 8). host_target(f1, 2).
% set-valued attributes become one fact per (family, token)
allergy(f3, peanut).      allergen(f7, peanut).
knows(f1, smith).         knows(f2, smith).
repel(f4, x).             repel(f9, x).
night(0..7).
% availability: derive can_attend from can_host
can_host(f1, 0).          can_attend(f2, 0).
can_attend(F,N) :- can_host(F,N).
```

This fact block is exactly the kind of human-auditable intermediate artifact the
project wants. It is a faithful, line-by-line transcription of the CSV.

### Decision variables (the "encoding")

Two natural choices:

```prolog
% who hosts on which night (a host "opens a table")
{ hosts(F,N) : can_host(F,N) } :- night(N).

% guest -> host assignment. A host counts as seated at its own table.
{ seat(G, H, N) : can_host(H,N) } 1 :- can_attend(G,N), night(N).
seat(H, H, N) :- hosts(H, N).            % host sits at own table
```

`seat(G,H,N)` = guest G is seated in H's home on night N. The cardinality bound
`... 1 :- ...` already enforces "at most one table per guest per night".

### Hard integrity constraints (`:-` "never true")

```prolog
% can only sit at a table that is actually hosting
:- seat(G,H,N), not hosts(H,N).

% availability: only seat people who can attend that night
:- seat(G,H,N), not can_attend(G,N).

% ALLERGY: guest's allergy meets host's allergen (set overlap)
:- seat(G,H,N), allergy(G,T), allergen(H,T).

% REPELS: two distinct guests sharing a repel token at the same table
:- seat(A,H,N), seat(B,H,N), A<B, repel(A,T), repel(B,T).

% CAPACITY: sum of seated sizes must not exceed host space
:- hosts(H,N), #sum { S,G : seat(G,H,N), size(G,S) } > Cap, space(H,Cap).

% HOST_TARGET: hard cap on number of hosting nights
:- family(H), host_target(H,K), #count { N : hosts(H,N) } > K.

% "EVERYONE FED": every available family is seated somewhere each night
:- can_attend(G,N), not seated(G,N).
seated(G,N) :- seat(G,_,N).
```

### Modeling gotchas

- **Set overlap is trivial and elegant** in ASP: shared variable `T` across two
  predicates *is* the intersection test. `allergy(G,T), allergen(H,T)` fires iff
  the token sets intersect. Same idiom for `repel`/`repel` and `knows`/`knows`.
  This is much cleaner than the Python set-intersection loops.
- **Capacity uses `#sum`** with the weight being the family size: `#sum { S,G : ... }`.
  The tuple key `S,G` (weight `S`, plus `G` to keep tuples distinct) is the
  standard idiom — without the extra `G` term, two families of equal size would
  collapse to one tuple and be undercounted. **This is a classic bug source.**
- **`size` includes the people attending; `space` includes the host themselves.**
  Since `seat(H,H,N)` is asserted, the host's own size is included in the `#sum`,
  matching the Python semantics (space counts the host).
- **Symmetry / table identity.** Tables are identified by their host, so there is
  no table-permutation symmetry to break — good. But guest-assignment symmetry
  across equivalent hosts can still slow optimization.
- **Grounding size** (see §4) is dominated by the `repel` co-seating constraint
  and by `seat(G,H,N)` which is O(families × hosts × nights).

---

## 2. Optimization in ASP — and the exponential-penalty problem

### The tools clingo gives you

Weak constraints and `#minimize`/`#maximize` attach a **weight** at a **priority
level**: syntax `[ weight@level, terms ]`.

```prolog
:~ seat(A,H,N), seat(B,H,N), A<B, novel(A,B). [-1@1, A,B,N]   % reward new meetings
#maximize { 1@1, A,B,N : ... }                                % equivalent form
```

Two distinct mechanisms, and choosing correctly is the crux:

- **Levels (`@p`) = lexicographic / priority order.** clingo optimizes the
  highest level first to optimality, then the next level *without worsening* the
  higher one. This is exactly "do A, then break ties by B."
- **Weights (`w`) at the *same* level = a single linear sum.** Everything at one
  level is added together; relative magnitudes trade off against each other.

So: **levels for "this objective strictly dominates that one"; weights for
"these terms trade off."** This maps directly onto the two-objective structure
(see §3).

### The hard part: the Python objective is NON-LINEAR and EXPONENTIAL

clingo optimization is **integer, linear sums over discrete priority levels**.
It has *no* native exponentiation, no real numbers, no `2**x` in the objective.
The current Python scores are deliberately exponential:

- host balance: `2**(52*|delta|)` where `delta` = ratio deviation
- empty seats: `2**(extra_seats)`
- diminishing returns on repeat meetings: `2 - 1/times`

These **cannot be represented faithfully**. Translation is necessarily lossy.
The idiomatic ASP approximations:

**(a) Steeply penalize imbalance — use bucketed/piecewise weights.**
Exponential penalty ≈ "each additional unit of deviation costs dramatically more
than the last." You approximate a convex penalty with a **staircase of weak
constraints at increasing weights** (and optionally increasing levels):

```prolog
% host_count(H,C): number of nights H hosts (computed via #count)
% deviation from a target band, penalized super-linearly by buckets:
:~ host_count(H,C), C >= 3. [10@1, H]     % 3rd dinner: cost 10
:~ host_count(H,C), C >= 4. [100@1, H]    % 4th: +100 (cumulative 110)
:~ host_count(H,C), C >= 5. [1000@1, H]   % 5th: +1000
```

Because the buckets are cumulative ("≥k" each fire), the marginal cost grows
geometrically — a genuine convex/exponential-like shape, expressed in integers.
You pre-compute the weights in Python and emit them. This is the standard way to
encode "very steep" penalties.

For the **ratio** balance specifically, ratios are fractional. Two options:
  - scale to integers: multiply ratio by a constant (e.g. work in
    `times_hosted * lcm_of_night_counts`) and penalize integer deviation buckets;
  - or penalize **squared deviation** via an auxiliary atom: pre-ground a table
    `dev_cost(D, W)` mapping each integer deviation `D` to weight `W = D*D` (or an
    exponential lookup), then `:~ host_dev(H,D), dev_cost(D,W). [W@1, H]`.
    The lookup-table trick lets you put *any* function (including `2**x`) into a
    linear weak constraint — you just enumerate it as facts. **This is the key
    technique for porting arbitrary nonlinear penalties.**

**(b) Empty seats `2**(extra_seats)`** — same lookup-table idiom:

```prolog
empty(H,N,E) :- hosts(H,N), space(H,Cap), used(H,N,U), E = Cap - U.
seatcost(0,0). seatcost(1,2). seatcost(2,4). seatcost(3,8). ...   % generated facts
:~ empty(H,N,E), seatcost(E,W). [W@1, H, N]
```

**(c) Diminishing returns on repeat meetings `2 - 1/times`** — model meetings as
a count and use a **concave reward staircase**: the 1st meeting of a pair is
worth most, each repeat worth less. Reward only the *first* co-seating fully and
give decreasing bonuses to repeats via "≥k" buckets with shrinking weights.
Often you simply reward distinct *novel* pairs once (`#maximize` over the set of
pairs ever co-seated who don't `knows` each other), which captures the dominant
intent and is far cheaper to ground.

**Honesty about loss:** the exponential weights blow up integer magnitudes fast.
clingo sums them as 64-bit integers; with `2**52` you are near the limit and risk
overflow / numeric domination exactly as the Python code warns. The right move is
**not** to replicate `2**(52*delta)` literally but to choose bucket weights that
preserve the *ordering* of solutions the author cares about (balance dominates
everything), then let lexicographic **levels** enforce the truly hard-dominance
relationships rather than relying on giant weights. Use weights only for *within-
level* trade-offs that genuinely should be commensurable.

---

## 3. Single model vs. two-stage

The current code is two-stage **for search-efficiency reasons** (random restart on
each), not because the objectives are truly independent. In ASP you have a third
option the Python code can't easily do: **one model, lexicographic priorities.**

```prolog
% Level 3 (highest): everyone fed   -- or make it a hard constraint
% Level 2: host balance             #minimize { ... @2 }
% Level 1: guest mixing / novelty    #maximize { ... @1 }
```

clingo will optimize level 3 to optimality, then 2 without worsening 3, then 1.
This **subsumes** the two-stage pipeline and is strictly more principled: stage 2
in the Python code is locked to whatever stage 1 picked, even if a slightly
different host schedule would enable far better mixing. A single lexicographic
model lets the solver trade a marginally-less-balanced host schedule for much
better mixing **only when balance allows ties** — which is usually what you want.

Trade-offs:
- **One model, lexicographic** — best solution quality; cleaner semantics; one
  program to maintain. Risk: larger grounding and a harder optimization problem;
  the top level must be reached optimally before lower levels improve, so if
  balance is expensive to prove optimal you may spend the whole budget there and
  never improve mixing. Mitigate with `--opt-strategy` and by capping levels.
- **Two ASP programs (mirror the current design)** — solve hosts (emit a host
  schedule as an auditable intermediate `.lp`), then solve guests against fixed
  hosts. Smaller, faster grounding per stage; each `.lp` is inspectable (great for
  the project's auditability value); easy to reason about. Cost: the same
  global-optimality loss the Python version already accepts.

**Recommendation: start with two ASP programs** (preserves the auditable
intermediate that the team values and keeps each solve small), but structure the
guest stage with lexicographic levels internally. Keep a single-model
lexicographic encoding as a documented experiment — if grounding/solve times are
acceptable at 40×8 it is the better answer.

---

## 4. Performance & anytime behavior

### Grounding scale

`seat(G,H,N)` grounds to roughly **|attendees| × |hosts| × |nights|**. For 40
families, ~40 possible hosts, 8 nights that is ~12,800 seat atoms — small. The
**repel co-seating** and **novel-pair** constraints are the blow-up risk: they are
O(pairs × hosts × nights) ≈ (40²/2) × 40 × 8 ≈ 250k ground rules in the naive
form. Mitigate by:
- only grounding pairs that actually share a `repel` token (guard with the fact),
- only grounding novel pairs that do *not* share a `knows` token,
- grounding meeting/novelty over `seat` joins lazily.

At this size grounding is not the problem; **proving optimality** is. Optimization
in ASP is `Σ²ᴾ`-ish in the worst case; clingo will often find good models quickly
but may not *prove* optimal within budget.

### Anytime / best-so-far (this matters a lot here)

clingo's default optimization (clasp, model-guided branch-and-bound) is
**anytime**: it emits a sequence of improving models, each better than the last,
and the **last one printed before interruption is the best found so far**. This is
exactly the behavior the time-bounded Python search has today.

- `--time-limit=<sec>` stops solving and returns the best model found.
- In the Python API, return `True`/`False` from the `on_model` callback or use a
  `SolveHandle` with `cancel()`; track the best `model.cost` yourself. Each
  `on_model` call gives you an improving model and its `cost` (a list of ints, one
  per priority level).
- `--opt-mode=opt` (default) = find one optimum (anytime improving models on the
  way). `--opt-mode=optN` = find an optimum **then enumerate all** equally-optimal
  models. `--opt-mode=ignore` ignores objectives. For this app `opt` is right.
- **Parallelism:** `--parallel-mode N` (alias `-t N`) runs N threads in a
  portfolio; combined with anytime optimization this is a strong, drop-in
  replacement for the current multiprocessing "run many, keep best." Default split
  search also works.

So the Python harness's "run for T seconds, keep the best" maps **directly** onto
`clingo --time-limit=T --parallel-mode=N` reading off the last/best model — and
clingo's branch-and-bound is generally far smarter than random restart.

---

## 5. Infeasibility ("everyone fed" can make instances UNSAT)

If you keep "everyone fed every night" as a **hard** constraint and a night lacks
the host capacity to seat everyone, the whole program is **UNSAT** — and a bare
clingo UNSAT gives you *no* schedule and no explanation. Patterns:

**(a) Detect UNSAT.** `ctl.solve()` returns a `SolveResult`; check
`result.unsatisfiable`. Trivial to detect; useless on its own.

**(b) Human-readable "why".** Two practical routes:
- **Pre-flight arithmetic checks in Python** before solving: for each night,
  compare `Σ size(available)` against `Σ space(possible hosts)`; if demand >
  supply, report "Night 3: 92 people need seats but hosts offer only 80." This is
  cheap, deterministic, and gives the clearest diagnostic. Strongly recommended as
  a first line.
- **UNSAT cores / relaxation in ASP:** turn the "fed" requirements into
  *assumption* atoms and use core extraction to find a minimal conflicting subset.
  This is powerful but the cores can be large and not very human-friendly without
  post-processing.

**(c) The idiomatic ASP answer — model "fed" as a top-priority weak constraint,
not a hard one.** Instead of `:- not seated(G,N).`, write:

```prolog
:~ can_attend(G,N), not seated(G,N). [1@9, G, N]   % level 9 = above all else
```

Now the program is **always SAT**: the solver seats as many people as possible,
and only leaves someone out when it is *physically impossible* to seat them. The
optimization cost at level 9 is literally the count of unfed family-nights, and
you can read out *exactly who* was left unseated and on which night — a perfect,
automatic diagnostic with graceful degradation. This mirrors the existing
`find_starved_family` "report, don't prevent" philosophy and is the recommended
design. Reserve a hard constraint only if "never run an infeasible event" is a
genuine business rule.

---

## 6. Python integration & auditability — API vs. CLI

**Option A: `clingo` Python package (in-process).**
`pip install clingo` ships prebuilt wheels (also `conda`/system packages). You
build a `Control`, `ctl.add(...)`/`ctl.ground(...)`/`ctl.solve(on_model=...)`,
read `model.symbols(shown=True)` and `model.cost`, set
`ctl.configuration.solve.{opt_mode,parallel_mode,models}` and
`...solver.seed`. Pros: no parsing of stdout, structured access to costs and
symbols, fine control over anytime callbacks and cancellation, multi-shot solving.
Cons: the facts/encoding live in memory — *less* inherently auditable unless you
deliberately also dump them.

**Option B: shell out to the `clingo` CLI** with a generated `.lp` facts file +
a static `encoding.lp`, then parse stdout (or `--outf=2` for **JSON** output,
which is far more robust to parse than the default text). Pros: the `.lp` files
*are* the audit trail — a human can open, diff, re-run them by hand
(`clingo encoding.lp instance.lp --time-limit=120 --parallel-mode=4`),
and reproduce any result independently of the Python harness. This matches the
project's stated value of human-auditable intermediate files and its existing
CSV-in/CSV-out, single-script ethos. Cons: parsing (use `--outf=2` JSON to
mitigate); marshalling args.

**Recommendation:** **Shell out to the CLI with generated `.lp` files and parse
`--outf=2` JSON.** It best serves auditability (the intermediate `.lp` for the
host stage and the guest stage are exactly the inspectable hand-off the team
wants), keeps the install story simple (a `clingo` binary, available via system
package or `pip install clingo` which also provides the CLI), and keeps the Python
side to "generate facts / run / parse," echoing the current architecture. Adopt
the Python API later only if you need multi-shot solving or tight anytime-callback
control. Note the dependency tradeoff: this *does* introduce clingo as an external
dependency, departing from the current "stdlib-only, no install step" property —
call that out explicitly to Chris.

---

## 7. Determinism & reproducibility

- **Single-threaded + fixed `--seed` ⇒ deterministic.** clingo/clasp with one
  solver thread and a fixed seed reproduces the same run (same models in the same
  order, same optimum) byte-for-byte across runs on the same binary/version.
- **Multi-threaded is NOT deterministic.** With `--parallel-mode N>1`, threads
  race; which improving models appear and the order of equally-optimal models
  vary run to run even with a fixed seed, because timing affects clause sharing
  and which thread reports first. The *proven optimum value* is stable, but the
  *witness* (the specific schedule) may differ.
- Practical guidance: for reproducible published schedules, do the final run
  **single-threaded with a fixed seed**, or run multi-threaded for speed and then
  **re-solve once single-threaded with the found optimum as a bound** to get a
  canonical witness. Pin the clingo version — optimization search can change
  across releases.

---

## Bottom line / recommendations

- **Q2 (objectives):** Use **levels (`@p`) for genuine dominance**
  (fed ≫ balance ≫ mixing) and **weights for within-level trade-offs**. You
  **cannot** port `2**(52*delta)` or `2**extra_seats` faithfully — clingo sums
  integers linearly. Approximate convex/exponential penalties with **cumulative
  "≥k" bucket weak constraints** and **pre-ground lookup-table facts**
  (`dev_cost(D,W)`) that encode any nonlinear function as data. Prefer
  lexicographic *levels* to enforce hard dominance over relying on astronomically
  large weights (which risk 64-bit overflow — the same domination hazard the
  Python comments warn about). The translation is **lossy**; aim to preserve the
  *ordering of preferred solutions*, not the exact numbers.
- **Q3 (one vs two stage):** A **single lexicographic model is more principled**
  and can beat the two-stage pipeline's quality (stage 2 isn't trapped by stage
  1's choice). But **start with two ASP programs** to preserve small, fast,
  *auditable* intermediate `.lp` hand-offs that match the project's values; keep
  single-model lexicographic as a documented experiment and switch to it if solve
  times at 40×8 are fine.
- **Q5 (infeasibility):** Model **"everyone fed" as a top-level weak constraint**
  (`[1@MAX]`), not a hard constraint. The program stays SAT, degrades gracefully,
  and the level-MAX cost names exactly who/which-night is unfed — an automatic
  diagnostic matching the existing "report starvation, don't prevent it" design.
  Add a cheap Python pre-flight capacity check per night for the clearest message.
- **Q6 (integration):** **Shell out to the `clingo` CLI** with generated `.lp`
  fact files and parse **`--outf=2` JSON**. Best auditability, simplest install,
  closest to the current single-script CSV-in/CSV-out architecture. Flag that this
  adds an external dependency (breaks the current stdlib-only property).
- **Anytime/perf:** clingo's default optimization is anytime; `--time-limit`
  + reading the last/best model replaces the current "run T seconds, keep best,"
  and `--parallel-mode N` replaces the multiprocessing portfolio — usually with
  much better solutions than random restart.
- **Determinism:** single thread + fixed seed = reproducible; multi-thread is not.
  Pin the clingo version.

---

## Sources

- Potassco guide / "A User's Guide to gringo, clasp, clingo & iclingo" (weight@level
  syntax, levels vs weights, optimization): https://github.com/potassco/guide
- clingo Python API — Control (add/ground/solve/on_model, configuration):
  https://potassco.org/clingo/python-api/current/clingo/control.html
- clingo Python API — solving (Model, cost, SolveHandle):
  https://potassco.org/clingo/python-api/current/clingo/solving.html
- clingo backend / add_minimize (weighted literal, weight, priority):
  https://potassco.org/clingo-preview/python-api/clingo/backend.html
- Gebser et al., "Multi-shot ASP solving with clingo" (incremental optimization,
  anytime, multi-shot): https://arxiv.org/pdf/1705.09811
- "Complex Optimization in Answer Set Programming" (lexicographic levels, Pareto):
  https://arxiv.org/pdf/1107.5742
- clingo issue #110 — opt-mode optN/topN semantics:
  https://github.com/potassco/clingo/issues/110
- clingo issue #318 — multiple minimization criteria / priority levels:
  https://github.com/potassco/clingo/issues/318
- clingo issue #337 — multi-threaded use / determinism caveats:
  https://github.com/potassco/clingo/issues/337
- "Unsatisfiability-based optimization in clasp" + core-guided / soft-constraint
  relaxation for graceful degradation (research summaries via search).
