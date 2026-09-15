"""KIO2 replay — FR-KIO2-02, post-mortem navigation over a recorded trace.

The engine (FocusTracer's ``ReplaySession``) already implements debugger-grade
navigation: Step Into / Over / Out, backward stepping, jump-to-crash, state
inspection and def-use. This module is the thin KIO2 layer that puts it on the
KIO contract, so the orchestrator, a UI or another KIO can drive a post-mortem
debugging session over ``/execute`` — that is the requirement's Output,
*"an API allowing a UI or a CLI to interact with the system"*.

Like the localizer, this is read-only: nothing here re-runs the program. Every
value returned is derived from the immutable recorded trace, which is what makes
the FR-KIO2-02 invariant hold — *"the state viewer presents the same data as
those that were recorded"*.

Stateless on purpose. Each call re-derives the timeline and returns the cursor
position, so the caller only has to keep an integer (``cursor``) between steps;
there is no server-side session to expire or to synchronise across replicas.
"""

from __future__ import annotations

from focustracer.core.replay import ReplaySession

from .contract import ReplayInput, ReplayView

_STEP_ACTIONS = ("into", "over", "out")


def replay(inp: ReplayInput) -> ReplayView:
    """Position a cursor in ``inp.trace_path`` and return the state recorded there."""
    try:
        session = ReplaySession.from_trace(inp.trace_path)
    except FileNotFoundError as exc:
        return ReplayView(
            status="FAILED", trace_path=inp.trace_path,
            message="Trace file not found.", error=str(exc),
        )
    except ValueError as exc:
        # Raised when the trace holds no line-level state (recorded too coarsely).
        return ReplayView(
            status="FAILED", trace_path=inp.trace_path,
            message="Trace has no replayable state — record with detail 'detailed'.",
            error=str(exc),
        )

    try:
        _seek(session, inp)
    except ValueError as exc:
        return ReplayView(
            status="FAILED", trace_path=inp.trace_path,
            message="Requested start point is not in the trace.", error=str(exc),
        )

    if inp.step > 0:
        session.step_forward(inp.step)
    elif inp.step < 0:
        session.step_back(-inp.step)
    if inp.step_action in _STEP_ACTIONS:
        session.step(inp.step_action, back=inp.back)

    view = session.to_dict(window=max(0, inp.window))
    def_of = _def_of(session, inp.def_var)
    cur = view["current"]

    return ReplayView(
        status="DONE",
        trace_path=inp.trace_path,
        cursor=view["cursor"],
        total=view["total"],
        can_forward=view["can_forward"],
        can_back=view["can_back"],
        current=cur,
        timeline=view["timeline"],
        def_of=def_of,
        message=f"Cursor {view['cursor']}/{view['total'] - 1} at "
                f"{cur.get('function')} L{cur.get('line')}: {cur.get('source')}",
    )


def _seek(session: ReplaySession, inp: ReplayInput) -> None:
    """Apply the requested start point. Order mirrors the engine CLI."""
    if inp.seq is not None:
        session.jump_to_seq(inp.seq)
    elif inp.at_event is not None:
        session.jump_to_event(inp.at_event)
    elif inp.at_line is not None:
        session.jump_to_line(inp.at_line, inp.function)
    elif inp.at_exception:
        session.jump_to_exception()
    # else: leave the cursor at the start of execution


def _def_of(session: ReplaySession, name: str | None) -> dict | None:
    """Def-use: the statement that last gave ``name`` its value at the cursor."""
    if not name:
        return None
    site = session.def_of(name)
    if site is None:
        return None
    m = site.moment
    return {
        "name": site.name, "seq": m.seq, "function": m.function,
        "line": m.line, "source": m.source,
        "from": site.old_value, "to": site.new_value,
    }
