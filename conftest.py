"""Pytest config: exposes the examples fixture and quiets the solver's stray
log output. The actual helpers live in tests/_support.py (pytest-free) so
non-test tools can import them too.
"""
import logging

import pytest

from tests._support import EXAMPLES

# find_schedule/optimize_schedule emit log.warning("runs: ...") via the
# multiprocessing logger; silence it so test output stays clean.
logging.getLogger("multiprocessing").setLevel(logging.ERROR)


@pytest.fixture
def examples_dir():
    return EXAMPLES
