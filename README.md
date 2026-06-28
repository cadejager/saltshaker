# saltshaker
Dinners with all!

## Testing & auditing

The test harness uses `pytest`, run via [`uv`](https://docs.astral.sh/uv/) (no separate install step needed). From the repo root:

    uv run pytest

Audit any input/output CSV pair by hand (prints any hard-constraint violations; `--metrics` adds a JSON quality summary on stdout):

    python3 -m saltshaker.validate_cli examples/in/a2_in.csv examples/out/a2_out.csv --metrics

Regenerate the committed quality baselines after an intentional change:

    python3 tools/update_baselines.py
