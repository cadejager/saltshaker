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
