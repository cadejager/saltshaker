"""Helpers shared by the test suite AND tools/update_baselines.py.

Deliberately imports nothing from pytest, so the baseline tool can run the
solver without pytest installed. `run_solver` runs the real two-stage solver
from schedule.py in-process (no multiprocessing, no file output) so callers can
inspect the produced schedule directly. `time=0` makes each search stage stop
after its first ~1000-iteration batch — fast, but still exercising the real
generate/score/fill code paths.
"""
import argparse
import pathlib

from schedule import read_csv, find_schedule, optimize_schedule, Family

# _support.py lives in tests/, so the repo root is two levels up.
EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples" / "in"


def run_solver(input_csv, time=0, max_dinner_size=8):
    families = read_csv(str(input_csv), max_dinner_size)
    args = argparse.Namespace(time=time)
    host_schedule = find_schedule(args, families)
    schedule = optimize_schedule(args, families, host_schedule, None)
    return families, schedule


def mkfam(email, size=1, space=8, host_target=None, allergies=(), allergens=(),
          knows=(), repel=(), attend=None, host=None, nights=1):
    attend = [True] * nights if attend is None else list(attend)
    host = [False] * nights if host is None else list(host)
    return Family(email, size, space, host_target, frozenset(allergies),
                  frozenset(allergens), frozenset(knows), frozenset(repel),
                  attend, host, sum(attend))
