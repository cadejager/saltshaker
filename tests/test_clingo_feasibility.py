import pytest

from schedule import read_csv
from saltshaker.clingo_solver import solve
from saltshaker.constraints import validate
from saltshaker.metrics import measure

EXAMPLES = ["a2_in.csv", "anonymised_in.csv", "example_in.csv"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_clingo_feeds_everyone_and_is_valid(name, examples_dir):
    families = read_csv(str(examples_dir / name), 8)
    schedule = solve(families, seed=0)
    assert validate(families, schedule) == [], \
        "%s: %s" % (name, [v.message for v in validate(families, schedule)])
    assert measure(families, schedule).unfed_count == 0, "%s left families unfed" % name
