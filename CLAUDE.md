# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Saltshaker schedules a series of rotating progressive-style dinners across a set of nights. Given families/groups who can attend or host on various nights, it produces a per-night assignment of guests to host homes that maximizes how many *new* people each family meets, while honoring hard constraints (allergies, repels, host availability, seating capacity).

The entire program is a single script: `schedule.py`. It depends only on the Python 3 standard library — there is no build step, no dependencies to install, and no test suite.

## Collaboration workflow

How Chris (the maintainer) and Claude work together on this repo. These are firm rules, not suggestions.

- **Never commit to `main`.** Don't commit anything anywhere until Chris explicitly says he's ready, and even then only onto a working branch.
- **Branch immediately for new work.** When starting a task while on `main`, create a dedicated working branch off `main` right away and do all edits there. This keeps `main`'s tree pristine. (Don't commit until told — the branch just isolates the work.)
- **Delivering work.** Finished changes live in the working directory for Chris to inspect — either uncommitted, or as commits on the working branch they were developed on.
- **Organizational sub-branches are encouraged.** Feel free to create extra branches to structure work. After discussing, they get merged into the current working branch.
- **Chris owns GitHub.** He pushes; Claude has no push access and never pushes.
- **`gh` is read-only for Claude.** Use the `gh` CLI freely to *inspect* the repo on GitHub (PRs, issues, CI, diffs), but never to write/push/comment/merge.
- **Subagents run in separate git worktrees** (`isolation: "worktree"`) so their edits never collide with the main tree or each other.
  - *Integrating a single subagent's output:* by default, review its diff and apply the relevant changes into the working branch yourself, then discard the worktree. If uncertain how something should integrate, ask Chris first.
  - *Multiple agents on the same problem:* do **not** auto-apply. Keep each agent's work in its own worktree/branch and present them so Chris and Claude can compare the approaches together before anything is applied.

## Running

```bash
./schedule.py <input.csv> <output.csv> [options]
```

Options:
- `-t, --time <seconds>` — wall-clock time budget *per stage* (default 120). The scheduler runs randomized search for this long twice (see Two-stage pipeline).
- `-p, --processes <n>` — parallel worker processes (default: `os.cpu_count()`). With `n > 1`, each stage spawns `n` workers and keeps the best result; with `n == 1` it runs inline (no multiprocessing).
- `-s, --max_dinner_size <n>` — caps every host's effective seating capacity (default 8). Applied at CSV-read time by clamping each family's `space`.
- `-l, --log <LEVEL>` — DEBUG/INFO/WARNING/ERROR/CRITICAL (default WARNING). Progress, scores, and starvation warnings go to **stderr** via `multiprocessing.log_to_stderr`; the schedule itself is the output CSV.

Example using the bundled data:
```bash
./schedule.py examples/in/example_in.csv /tmp/out.csv -t 5 -l INFO
```

## Input / output format

**Input CSV** (see `examples/in/`): one row per family. The first row is a header and is skipped. Columns are positional, not by name — `read_csv` reads them by index, so column *order* matters but header *text* does not:

0. `email` — unique identifier for the family
1. `size` — people attending
2. `space` — people they can seat *including themselves* (0 = cannot host)
3. `host_target` — optional hard cap on number of times they host; blank = no target (treated as a flexible host whose host count is balanced by ratio)
4. `allergies` — space-separated tokens; this family will not enter a home whose `allergens` intersect these
5. `allergens` — space-separated tokens present in this family's home when hosting
6. `knows` — space-separated tokens; meeting families with overlapping `knows` yields **no** "new meeting" bonus
7. `repels` — space-separated tokens; two families with overlapping `repels` are never seated together
8+. one column per night, each `Can Host` / `Can Attend` / `Cannot Attend`. `Can Host` implies can attend.

All families must have the same number of night columns. Example inputs use varying header labels (`a2_in.csv`, `anonymised_in.csv`, `example_in.csv`) — only the column positions are load-bearing.

**Output CSV** (see `examples/out/`): one row per dinner (host) per night, columns `Night, Size, Space, Host, Attendees`. `Night` is a 0-based index. `Attendees` is a comma-space list of emails and always includes the host.

## Architecture: two-stage pipeline

The core idea is that host placement and guest mixing are scored by different objectives, so `main()` optimizes them in two sequential stages. Both stages use the same "generate many random candidates, keep the best" search (random restart, *not* simulated annealing — see the comment above `find_schedule`).

**Stage 1 — host scheduling** (`find_schedule` → `generate_host_schedule`, scored by `score_host`)
Decides *who hosts on which night* and nothing else. `generate_host_schedule` walks nights in random order and, within a night, assigns hosts to cover each distinct allergy-group's seating demand, prioritizing families with an explicit `host_target` before flexible hosts. `score_host` rewards balanced hosting (penalizes deviation of each flexible host's hosting *ratio* — times hosted / nights available — from the average, very steeply: `2**(52*|Δ|)`), penalizes total dinner count, and penalizes back-to-back-night repeat hosting. Output is a schedule where each host maps to a set containing only themselves.

**Stage 2 — guest filling** (`optimize_schedule` → `fill_schedule`, scored by `score_guest`)
Takes the fixed host schedule from stage 1 and repeatedly fills guests into the open seats, keeping the best mixing. `fill_schedule` shuffles unassigned families and greedily seats each into a random valid host (respecting allergy conflicts, remaining capacity, and repels). `score_guest` strongly rewards total meals served (`128 * meals` — feeding everyone dominates), rewards new distinct meetings (skipping pairs that already `knows` each other), and penalizes hosts left with many empty seats.

`main()` runs stage 1 across workers, picks the highest `score_host` result, then runs stage 2 across workers on that fixed host schedule and picks the highest `score_guest` result. Finally it logs summaries and runs `find_starved_family` to warn (stderr) about any family that was available on a night but got no dinner — starvation is reported, not prevented, so check the logs.

## Things to know when modifying

- **`Family` identity is its email.** `__eq__`/`__hash__` use only `email`, and families are used as dict keys and set members throughout. Two `Family` objects with the same email are interchangeable.
- **`score_host` and `host_summery` duplicate logic**, as do `score_guest` and `summery`. The `*_summery` functions are logging-only views; the `score_*` functions are the real objective. Keep them consistent if you change scoring.
- **Scores are unbounded relative magnitudes**, hand-tuned via exponential penalties. Changing one weight (e.g. the ratio penalty base/exponent in `score_host`, or the meal bonus in `score_guest`) can dominate all others. The git history shows these constants are iterated on deliberately.
- **Hard vs. soft constraints:** allergies and repels are *hard* (enforced in the generator/filler, never violated). `host_target` is a hard cap on hosting count. Hosting *balance*, dinner count, and meeting novelty are *soft* (expressed only through scores).
- **Search is time-bounded, not convergence-bounded.** Both search loops run until the `-t` budget elapses (checked every ~1000 iterations); there is no early-stop on plateau. Several `TODO`s in the code note this and other intended improvements (smarter host ordering, most-restrictive-allergy-first).
- The code contains numerous original-author spelling variants in identifiers and logs (`summery`, `penility`, `peniltiy`, `immproved`). Match existing names when editing rather than "fixing" them, to avoid breaking references.
