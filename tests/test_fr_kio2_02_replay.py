"""FR-KIO2-02 acceptance — Trace Capture & Replay over the KIO2 contract.

Acceptance criteria: *"Forward/Backward navigation behaves identically to a
standard debugger. State reconstruction matches recorded snapshots exactly."*
Invariant: *"The state viewer presents the same data as those that were
recorded."* Output: *"An API allowing a UI or a CLI to interact with the
system."*

The engine's own stepping mechanics are covered in FocusTracer
(``tests/test_replay.py``); what is pinned here is KIO2's surface — that the
behaviour reaches a caller through ``kio2.replay`` and through ``/execute``.
"""

import asyncio

from kio2 import localize, replay
from kio2.contract import ReplayInput
from kio2.dummy import dummy_input
from kio2.service import _SUPPORTED_TASKS, TASK_REPLAY, kio2_handler


def _run(trace, **kw):
    return replay(ReplayInput(trace_path=trace, **kw))


# ── navigation behaves like a debugger ──────────────────────────────────────


def test_step_into_advances_exactly_one_line(trace_set):
    first = _run(trace_set["two_a"], seq=0)
    stepped = _run(trace_set["two_a"], seq=0, step_action="into")
    assert first.status == "DONE"
    assert stepped.cursor == first.cursor + 1


def test_forward_then_backward_returns_to_the_same_point(trace_set):
    """Backward navigation is the exact inverse of forward — the FR-02 promise."""
    start = _run(trace_set["two_a"], seq=4)
    fwd = _run(trace_set["two_a"], seq=4, step=3)
    back = _run(trace_set["two_a"], seq=fwd.cursor, step=-3)
    assert fwd.cursor == start.cursor + 3
    assert back.cursor == start.cursor
    assert back.current["state"] == start.current["state"]


def test_step_over_skips_the_called_frame(trace_set):
    """From the call site in summarise_cart, Step Over must not enter average_price."""
    at_call = _run(trace_set["two_a"], at_line=11, function="summarise_cart")
    assert at_call.status == "DONE"
    over = _run(trace_set["two_a"], at_line=11, function="summarise_cart", step_action="over")
    assert over.current["depth"] <= at_call.current["depth"]
    assert over.current["function"] == "summarise_cart"


def test_step_out_leaves_the_current_frame(trace_set):
    inner = _run(trace_set["two_a"], at_line=6, function="average_price")
    out = _run(trace_set["two_a"], at_line=6, function="average_price", step_action="out")
    assert inner.current["function"] == "average_price"
    assert out.current["depth"] < inner.current["depth"]


def test_step_backward_with_a_debugger_action(trace_set):
    fwd = _run(trace_set["two_a"], seq=5)
    back = _run(trace_set["two_a"], seq=5, step_action="into", back=True)
    assert back.cursor == fwd.cursor - 1


def test_jump_to_exception_lands_on_the_fault(trace_set):
    crash = _run(trace_set["crash"], at_exception=True)
    assert crash.status == "DONE"
    assert "len(prices)" in crash.current["source"]


# ── state reconstruction matches what was recorded ──────────────────────────


def test_state_matches_the_localizer_crash_state():
    """Same recorded moment, two code paths ⇒ identical state (the FR-02 invariant)."""
    loc = localize(dummy_input())
    assert loc.status == "DONE"
    view = _run(loc.trace_path, at_exception=True)
    replayed = {k: v["value"] for k, v in view.current["state"].items()}
    recorded = {k: v["value"] for k, v in loc.crash_state.items()}
    assert replayed == recorded


def test_def_use_reports_the_defining_statement(trace_set):
    view = _run(trace_set["two_a"], at_line=7, function="average_price", def_var="total")
    assert view.def_of is not None
    assert view.def_of["name"] == "total"
    assert "total" in view.def_of["source"]


def test_timeline_window_is_returned_for_a_scrubber(trace_set):
    view = _run(trace_set["two_a"], seq=4, window=2)
    assert view.timeline
    assert any(e["seq"] == view.cursor for e in view.timeline)
    assert len(view.timeline) <= 5      # cursor ± window


# ── the API surface (Output: "an API allowing a UI or a CLI") ───────────────


def test_replay_is_an_announced_task():
    assert any(t["task_type"] == TASK_REPLAY for t in _SUPPORTED_TASKS)


def test_handler_routes_an_explicit_replay_task(trace_set):
    async def _go():
        payload = {"task_type": TASK_REPLAY, "trace_path": trace_set["two_a"], "seq": 2}
        env = type("E", (), {"payload": payload, "session_id": "s-replay"})()
        return await kio2_handler(env)

    out = asyncio.run(_go())
    assert out["status"] == "DONE"
    assert out["artifact_data"]["task_type"] == TASK_REPLAY
    assert out["artifact_data"]["cursor"] == 2
    assert out["artifact_data"]["current"]["source"]


def test_handler_infers_replay_from_the_payload_shape(trace_set):
    """A payload with trace_path and no task_type is still a replay request."""
    async def _go():
        env = type("E", (), {"payload": {"trace_path": trace_set["two_a"]}, "session_id": "s"})()
        return await kio2_handler(env)

    assert asyncio.run(_go())["artifact_data"]["task_type"] == TASK_REPLAY


def test_missing_trace_fails_cleanly():
    view = _run("/no/such/trace_xyz.xml")
    assert view.status == "FAILED"
    assert view.error


def test_unknown_start_point_fails_cleanly(trace_set):
    view = _run(trace_set["two_a"], at_line=99999)
    assert view.status == "FAILED"
    assert view.error
