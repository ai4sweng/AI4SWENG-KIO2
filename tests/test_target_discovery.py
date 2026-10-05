"""Tracing a project without being told which functions to trace.

KIO2's callers know *which run failed*, not *which functions to instrument* — an
upstream KIO hands over a failing test or a runtime log. The contract documents
``functions`` as optional ("empty ⇒ trace all"), so a payload without it has to
work on a realistic, multi-module project whose entry point defines no functions
of its own.
"""

import pytest

from kio2 import localize
from kio2.contract import Kio2Input
from kio2.runner import MAX_AUTO_TARGETS, RunnerError, discover_functions, run_trace

PRICING = '''
TAX = 0.20


def net_price(item):
    return item["price"] * item["qty"]


def discounted(net, tier):
    rate = {"gold": 0.20, "silver": 0.10}[tier]   # KeyError for unknown tiers
    return net * (1 - rate)


def gross(net):
    return net * (1 + TAX)
'''

ORDERS = '''
from shop.pricing import discounted, gross, net_price


def order_total(items, tier):
    net = 0
    for it in items:
        net += net_price(it)
    after = discounted(net, tier)
    return round(gross(after), 2)
'''

MAIN = '''
from shop.orders import order_total

CART = [{"price": 100, "qty": 2}, {"price": 30, "qty": 1}]

if __name__ == "__main__":
    print(order_total(CART, "bronze"))
'''


@pytest.fixture
def project(tmp_path):
    """A package-shaped program that crashes, with an entry point holding no defs."""
    pkg = tmp_path / "shop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "pricing.py").write_text(PRICING, encoding="utf-8")
    (pkg / "orders.py").write_text(ORDERS, encoding="utf-8")
    (tmp_path / "main.py").write_text(MAIN, encoding="utf-8")
    return tmp_path


# ── discovery ───────────────────────────────────────────────────────────────


def test_discovery_reaches_functions_in_other_modules(project):
    found, notes = discover_functions(project / "main.py", project)
    assert set(found) == {"order_total", "net_price", "discounted", "gross"}
    assert notes == []


def test_discovery_prefers_code_next_to_the_entry_point(tmp_path):
    """A truncated list must keep the code nearest the entry point."""
    (tmp_path / "sibling.py").write_text("def near():\n    pass\n", encoding="utf-8")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "far.py").write_text("def far_away():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def entry():\n    pass\n", encoding="utf-8")

    found, _ = discover_functions(tmp_path / "main.py", tmp_path)
    assert found.index("entry") < found.index("far_away")
    assert found.index("near") < found.index("far_away")


def test_discovery_skips_virtualenvs_and_caches(project):
    noise = project / ".venv" / "lib"
    noise.mkdir(parents=True)
    (noise / "vendored.py").write_text("def should_not_be_traced():\n    pass\n", encoding="utf-8")
    cache = project / "__pycache__"
    cache.mkdir()
    (cache / "stale.py").write_text("def also_not():\n    pass\n", encoding="utf-8")

    found, _ = discover_functions(project / "main.py", project)
    assert "should_not_be_traced" not in found
    assert "also_not" not in found


def test_discovery_survives_an_unparsable_file(project):
    (project / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    found, _ = discover_functions(project / "main.py", project)
    assert "order_total" in found          # the syntax error must not abort the scan


def test_discovery_reports_truncation(project):
    found, notes = discover_functions(project / "main.py", project, limit=2)
    assert len(found) == 2
    assert notes and "auto-discovered" in notes[0]


def test_discovery_finds_methods_too(tmp_path):
    (tmp_path / "m.py").write_text(
        "class Thing:\n    def method(self):\n        pass\n", encoding="utf-8"
    )
    found, _ = discover_functions(tmp_path / "m.py", tmp_path)
    assert "method" in found


# ── the whole pipeline, with no functions given ─────────────────────────────


def test_localize_without_functions_on_a_multi_module_project(project):
    """The regression this guards: a payload with no `functions` used to FAIL."""
    result = localize(Kio2Input(target_script="main.py", working_directory=str(project)))
    assert result.status == "DONE", result.error
    assert result.criterion.startswith("exception@")
    top = result.suspect_lines[0]
    assert top.dependency == "criterion"
    assert "[tier]" in top.source                       # the crashing subscript
    assert result.crash_state["tier"]["value"] == "'bronze'"


def test_slice_spans_modules(project):
    """Evidence from both modules, not just the crashing one."""
    result = localize(Kio2Input(target_script="main.py", working_directory=str(project)))
    functions = {s.function for s in result.suspect_lines}
    assert "discounted" in functions      # shop/pricing.py
    assert "order_total" in functions     # shop/orders.py


def test_explicit_functions_still_win(project):
    """Naming targets keeps working, and narrows the trace."""
    result = localize(Kio2Input(
        target_script="main.py", working_directory=str(project),
        functions=["discounted"],
    ))
    assert result.status == "DONE"
    assert {s.function for s in result.suspect_lines} == {"discounted"}


def test_a_project_with_no_functions_fails_with_a_clear_message(tmp_path):
    (tmp_path / "main.py").write_text("print('nothing to trace')\n", encoding="utf-8")
    with pytest.raises(RunnerError, match="no functions found"):
        run_trace("main.py", working_directory=str(tmp_path))


def test_default_limit_is_documented():
    assert MAX_AUTO_TARGETS > 0
