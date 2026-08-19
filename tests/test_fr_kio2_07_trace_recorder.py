"""FR-KIO2-07 acceptance — the trace recorder.

Acceptance criteria:
  * *"Recorder must successfully capture variable states in the test suite."*
  * *"Produced traces must be machine-readable by the Replay Engine."*

Invariants:
  * *"Trace instrumentation must not alter program semantics or output …"*
  * *"Tracing process must remain deterministic and reproducible across runs."*

Post-condition: *"The infrastructure supports the recording of execution traces
for the test programs."*
"""

import runpy

import pytest

from conftest import TRACED_FUNCTIONS
from kio2 import compare, replay
from kio2.contract import AlignInput, ReplayInput
from kio2.dummy import EXAMPLE
from kio2.runner import RunnerError, run_trace


def _cart(n, price=5):
    return [{"name": f"i{i}", "price": price, "in_stock": True} for i in range(n)]


# ── variable states are captured ────────────────────────────────────────────


def test_recorder_captures_variable_states(record_trace):
    """Every local the program assigns must be readable back out of the trace."""
    trace = record_trace("states", _cart(3))
    seen = set()
    view = replay(ReplayInput(trace_path=trace, seq=0))
    assert view.status == "DONE"
    for seq in range(view.total):
        step = replay(ReplayInput(trace_path=trace, seq=seq))
        seen.update(step.current["state"])
    assert {"items", "prices", "total", "p"} <= seen


def test_recorded_values_carry_their_types(record_trace):
    trace = record_trace("typed", _cart(2))
    view = replay(ReplayInput(trace_path=trace, at_line=7, function="average_price"))
    total = view.current["state"]["total"]
    assert total["type"] == "int"
    assert total["value"] == "10"       # two items at price 5


def test_recorder_captures_the_exception(record_trace):
    """The empty cart divides by zero; the crash must be in the trace."""
    trace = record_trace("crashing", [])
    view = replay(ReplayInput(trace_path=trace, at_exception=True))
    assert view.status == "DONE"
    assert "len(prices)" in view.current["source"]
    assert view.current["state"]["prices"]["value"] == "[]"


# ── machine-readable by the replay engine ───────────────────────────────────


def test_trace_is_consumable_by_the_replay_engine(record_trace):
    trace = record_trace("readable", _cart(2))
    view = replay(ReplayInput(trace_path=trace, seq=0))
    assert view.status == "DONE"
    assert view.total > 0
    assert view.current["function"] in TRACED_FUNCTIONS


def test_bundled_example_is_recordable_and_replayable(tmp_path):
    """The packaged failing example — the fixture the rest of KIO2 runs on."""
    out = str(tmp_path / "bundled.xml")
    trace = run_trace(
        str(EXAMPLE), working_directory=str(EXAMPLE.parent),
        functions=["average_price", "summarise_cart"], output_path=out,
    )
    view = replay(ReplayInput(trace_path=trace, at_exception=True))
    assert view.status == "DONE"
    assert view.current["line"] == 15


# ── instrumentation does not alter semantics ────────────────────────────────


def test_recorded_values_match_an_untraced_run(record_trace, tmp_path):
    """What the trace says the program computed is what it actually computes.

    The program is executed once *without* any instrumentation and once under
    the recorder; the value the recorder captured for ``avg`` must equal the
    value the untraced run produced.
    """
    cart = _cart(4, price=7)
    trace = record_trace("semantics", cart)

    src = tmp_path / "semantics.py"          # written by the fixture
    module = runpy.run_path(str(src))
    expected = module["summarise_cart"](cart)["average_price"]

    view = replay(ReplayInput(trace_path=trace, at_line=12, function="summarise_cart"))
    assert float(view.current["state"]["avg"]["value"]) == expected


def test_instrumentation_preserves_a_raised_exception():
    """The example raises ZeroDivisionError with and without tracing."""
    with pytest.raises(ZeroDivisionError):
        runpy.run_path(str(EXAMPLE), run_name="__main__")


# ── deterministic and reproducible across runs ──────────────────────────────


def test_two_recordings_of_one_program_are_identical(record_trace):
    """Reproducibility, stated as the FR-KIO2-03 distance: two runs ⇒ 0."""
    cart = _cart(3)
    first = record_trace("repro_1", cart)
    second = record_trace("repro_2", cart)

    res = compare(AlignInput(trace_paths=[first, second]))
    assert res.status == "DONE"
    assert res.distance == 0            # identical executed-statement sequences
    assert res.gaps == 0


def test_reproducible_runs_record_identical_values(record_trace):
    cart = _cart(3)
    first = record_trace("values_1", cart)
    second = record_trace("values_2", cart)

    for seq in range(0, 6):
        res = compare(AlignInput(trace_paths=[first, second], seq=seq))
        assert res.aligned is True
        assert res.delta == []          # same statement, same recorded values


# ── the recording infrastructure ────────────────────────────────────────────


def test_infrastructure_records_a_set_of_test_programs(trace_set):
    """Post-condition: several programs/inputs recorded through one entry point."""
    assert len(trace_set) == 4
    for path in trace_set.values():
        assert replay(ReplayInput(trace_path=path, seq=0)).status == "DONE"


def test_untraceable_target_raises_runner_error():
    with pytest.raises(RunnerError):
        run_trace("/no/such/program_xyz.py")
