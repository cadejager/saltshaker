"""In-process clingo feasibility solver: produce a valid, everyone-fed schedule.

Optimizes only minimize-unfed (no host-balance / mixing objectives yet — that is
phase 2). Single-threaded + seeded for reproducibility; dumps the exact ASP program
to a .lp file for audit. See 2026-06-27-clingo-feasibility-design.md.
"""
import clingo

from saltshaker import asp
from saltshaker import balance


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
