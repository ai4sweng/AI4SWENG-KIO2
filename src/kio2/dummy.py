"""Dummy upstream input for standalone KIO2 runs.

Until KIO2 is wired to real upstream KIOs (e.g. KIO11 test automation providing
the failing test), this supplies the same envelope shape from a bundled failing
example so KIO2 can run end-to-end on its own.
"""

from __future__ import annotations

from pathlib import Path

from .contract import Kio2Input

EXAMPLE = Path(__file__).parent / "examples" / "buggy_order_total.py"


def dummy_input() -> Kio2Input:
    """A Kio2Input pointing at the bundled failing example (ZeroDivisionError)."""
    return Kio2Input(
        target_script=str(EXAMPLE),
        working_directory=str(EXAMPLE.parent),
        functions=["average_price", "summarise_cart"],
        failing_test="test_summarise_cart_empty_stock — ZeroDivisionError in average_price",
    )


def dummy_payload() -> dict:
    """The dummy input as an envelope payload dict (for /execute testing)."""
    return dummy_input().to_payload()
