"""Smoke test — the package imports and exposes a version.

Replaced/extended by the conformance harness tests in a later build step.
"""

import openmarina


def test_version_present():
    assert isinstance(openmarina.__version__, str)
    assert openmarina.__version__
