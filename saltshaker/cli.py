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
