"""Shared fixtures — record traces of one program under different inputs.

FR-KIO2-03's Input is *"a set of execution traces relating to a single program
ran with the different inputs and configurations"*, so the alignment and replay
acceptance tests need several traces of the **same** source. The factory below
writes one program (a variant of the bundled failing example) and records it
with whatever cart is passed in, which is exactly that set.
"""

import pytest

from kio2.runner import run_trace

# One program, parameterised by its input. An empty in-stock cart reproduces the
# bundled ZeroDivisionError; a non-empty one completes normally.
PROGRAM = '''
def average_price(items):
    prices = [it["price"] for it in items if it["in_stock"]]
    total = 0
    for p in prices:
        total += p
    return total / len(prices)


def summarise_cart(items):
    avg = average_price(items)
    return {"count": len(items), "average_price": avg}


if __name__ == "__main__":
    print(summarise_cart(__CART__))
'''

TRACED_FUNCTIONS = ["average_price", "summarise_cart"]


def _cart(n_in_stock: int, price: int = 5) -> list[dict]:
    return [{"name": f"i{i}", "price": price, "in_stock": True} for i in range(n_in_stock)]


def _record(tmp_dir, name: str, cart: list[dict]) -> str:
    """Write the program with ``cart`` baked in and record a trace of it."""
    src = tmp_dir / f"{name}.py"
    src.write_text(PROGRAM.replace("__CART__", repr(cart)), encoding="utf-8")
    return run_trace(
        str(src),
        working_directory=str(tmp_dir),
        functions=TRACED_FUNCTIONS,
        output_path=str(tmp_dir / f"{name}.xml"),
    )


@pytest.fixture
def record_trace(tmp_path):
    """Function-scoped factory: ``record_trace(name, cart) -> trace path``."""
    def make(name: str, cart: list[dict]) -> str:
        return _record(tmp_path, name, cart)
    return make


@pytest.fixture(scope="module")
def trace_set(tmp_path_factory):
    """A curated set of traces of one program, recorded once per test module.

    - ``two_a`` / ``two_b`` — the same input recorded twice ⇒ distance 0;
    - ``five``              — a longer loop ⇒ genuine divergence;
    - ``crash``             — the empty cart ⇒ the recorded ZeroDivisionError.
    """
    d = tmp_path_factory.mktemp("traceset")
    return {
        "two_a": _record(d, "two_a", _cart(2)),
        "two_b": _record(d, "two_b", _cart(2)),
        "five": _record(d, "five", _cart(5)),
        "crash": _record(d, "crash", []),
    }
