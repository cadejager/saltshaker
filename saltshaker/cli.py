"""CLI for the clingo objectives solver:

    uv run python -m saltshaker.cli <input.csv> <output.csv> [-s N] [--seed N] [--time-limit S] [--lp PATH]

Reads the input CSV, runs the one-stage two-pass objectives solve (proven-optimal
host-balance, then best-found mixing within the --time-limit budget), writes the
output CSV, dumps the ASP program to <output>.lp (or --lp PATH), and prints a
one-line summary (meals/dinners/unfed/new_meetings/host-balance) to stderr.
"""
import argparse
import sys

from schedule import read_csv, write_csv
from saltshaker import clingo_solver
from saltshaker.metrics import measure


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Schedule saltshaker dinners with clingo (objectives)")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("-s", "--max-dinner-size", type=int, default=8,
                        help="cap every host's seating capacity (default 8)")
    parser.add_argument("--seed", type=int, default=0, help="clingo seed (reproducibility)")
    parser.add_argument("--time-limit", type=int, default=60,
                        help="seconds for the mixing pass (default 60; balance always proves fast)")
    parser.add_argument("--lp", default=None, help="path for the ASP dump (default: <output>.lp)")
    args = parser.parse_args(argv)

    lp_path = args.lp if args.lp is not None else args.output + ".lp"
    families = read_csv(args.input, args.max_dinner_size)
    schedule = clingo_solver.solve_optimized(
        families, seed=args.seed, time_limit=args.time_limit, lp_path=lp_path)
    write_csv(args.output, schedule)

    m = measure(families, schedule)
    hb = m.host_balance
    dev = "%.4f" % hb["max_deviation"] if hb else "n/a"
    print("meals=%d dinners=%d unfed=%d new_meetings=%d host_balance_maxdev=%s"
          % (m.meals, m.dinners, m.unfed_count, m.new_meetings, dev), file=sys.stderr)
    for email, night in m.unfed:
        print("UNFED: %s night %d" % (email, night), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
