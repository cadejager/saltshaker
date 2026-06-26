"""CLI: audit an (input.csv, output.csv) schedule pair against H1-H8.

    python -m saltshaker.validate_cli INPUT.csv OUTPUT.csv [--metrics]

Exit status: 0 = clean, 1 = hard-constraint violations found, 2 = malformed input.
"""
import argparse
import json
import sys

from saltshaker.constraints import validate
from saltshaker.metrics import measure
from saltshaker.schedule_io import load_output_csv, OutputCsvError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit a saltshaker schedule")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--metrics", action="store_true",
                        help="also print quality metrics as JSON to stdout")
    args = parser.parse_args(argv)

    try:
        families, schedule, warnings = load_output_csv(args.input, args.output)
    except OutputCsvError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2

    for w in warnings:
        print("WARNING: %s" % w, file=sys.stderr)

    violations = validate(families, schedule)
    for v in violations:
        print("%s night %s: %s" % (v.rule, v.night, v.message), file=sys.stderr)

    if args.metrics:
        print(json.dumps(measure(families, schedule).to_dict(),
                         indent=2, sort_keys=True))

    if violations:
        print("%d violation(s)" % len(violations), file=sys.stderr)
        return 1
    print("OK: no hard-constraint violations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
