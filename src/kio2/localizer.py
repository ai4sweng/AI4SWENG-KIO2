"""KIO2 core — fault localization from a recorded execution.

Pipeline (all read-only over the trace, no re-run beyond the initial capture):

    target → [runner] trace → [slicer] backward dynamic slice
           → ranked suspect lines (+ crash state, + KIO7 hand-off context)

This module has NO dependency on the AI4SWENG platform or on any transport.
It depends only on ``focustracer`` and this package's contract, so it runs
identically as a library call, inside ``make_kio_app``, or in the standalone
KIO2 repository.
"""

from __future__ import annotations

from focustracer.core.explain import build_slice_context
from focustracer.core.reverse import result_to_dict, reverse_trace
from focustracer.core.slicer import slice_result_to_dicts, slice_trace

from .contract import FaultLocalization, Kio2Input, SuspectLine
from .runner import RunnerError, run_trace

# Evidence weighting: the crash/criterion statement matters most, then the
# control-flow statements that led there, then the data feeding it.
_DEP_SCORE = {"criterion": 1.0, "control": 0.75, "data": 0.5}
_HITL_THRESHOLD = 0.6


def localize(inp: Kio2Input) -> FaultLocalization:
    """Localise the fault for ``inp`` and return ranked suspect statements."""
    # 1) Record the failing execution. An empty `functions` means "trace
    #    everything": the runner discovers the targets from the project, and any
    #    remark about that discovery comes back in `notes` for the message.
    notes: list[str] = []
    try:
        trace_path = run_trace(
            inp.target_script,
            working_directory=inp.working_directory,
            functions=inp.functions,
            detail=inp.detail,
            schema_version=inp.schema_version,
            notes=notes,
            **({"timeout": inp.trace_timeout} if inp.trace_timeout else {}),
        )
    except RunnerError as exc:
        return FaultLocalization(status="FAILED", message="Could not trace the target.", error=str(exc))

    at_exception = inp.criterion is None

    # 2) Backward dynamic slice from the crash (or a given criterion).
    try:
        model, result = slice_trace(
            trace_path, at_exception=at_exception, at=inp.criterion, include_control=True
        )
    except ValueError as exc:
        # A target that ran to completion is not an analysis failure — there was
        # simply nothing to localise. Callers ask KIO2 to check code that may or
        # may not be broken (an orchestrator step, a CI hook), so "clean run" has
        # to be a successful answer; reporting it as FAILED would make every
        # healthy program look like a broken service.
        if at_exception and not _has_recorded_exception(trace_path):
            return FaultLocalization(
                status="DONE", trace_path=trace_path, confidence=1.0,
                message="No runtime defect observed: the target ran to completion "
                        "without raising. Nothing to localise.",
            )
        return FaultLocalization(
            status="FAILED", trace_path=trace_path,
            message="Slicing failed — the trace has no exception/criterion or no reads (needs detailed, schema>=2.3).",
            error=str(exc),
        )

    nodes = slice_result_to_dicts(model, result)
    if not nodes:
        return FaultLocalization(
            status="REVIEW_REQUIRED", trace_path=trace_path, criterion=result.criterion_label,
            confidence=0.2, message="No statements in the slice — manual review needed.",
        )

    # 3) Rank suspect lines (dedupe by file:line, keep the strongest evidence).
    best: dict[tuple[str, int], dict] = {}
    for idx, n in enumerate(nodes):
        key = (n.get("file", ""), n["line"])
        score = _DEP_SCORE.get(n["dependency"], 0.4)
        prev = best.get(key)
        if prev is None or score > prev["_score"]:
            best[key] = {**n, "_score": score, "_idx": idx}

    ordered = sorted(best.values(), key=lambda d: (-d["_score"], d["_idx"]))
    suspects = [
        SuspectLine(
            rank=i + 1, score=round(d["_score"], 3), dependency=d["dependency"],
            file=d.get("file", ""), function=d.get("function") or "?",
            line=d["line"], source=d.get("source", ""),
        )
        for i, d in enumerate(ordered)
    ]

    # 4) Crash state (best-effort) via reverse execution.
    crash_state: dict = {}
    try:
        rev = reverse_trace(
            trace_path, at_exception=at_exception,
            at_line=None if at_exception else _line_of(inp.criterion),
            step_back=0,
        )
        crash_state = result_to_dict(rev)["target"].get("state", {})
    except Exception:  # noqa: BLE001 — crash state is a nice-to-have
        crash_state = {}

    # 5) Hand-off context for KIO7 (the slice, value-annotated).
    try:
        handoff = build_slice_context(model, result)
    except Exception:  # noqa: BLE001
        handoff = ""

    # 6) Confidence + HITL gating.
    has_criterion = any(s.dependency == "criterion" for s in suspects)
    confidence = 0.85 if has_criterion else 0.55
    if len(suspects) > 25:  # very large slice ⇒ noisier localization
        confidence -= 0.1
    confidence = round(max(0.0, min(1.0, confidence)), 2)

    status = "DONE" if confidence >= _HITL_THRESHOLD else "REVIEW_REQUIRED"
    top = suspects[0]
    msg = f"Localised to {top.function} L{top.line}: {top.source}  ({len(suspects)} suspect statement(s))"
    if notes:
        msg += "  [" + "; ".join(notes) + "]"

    return FaultLocalization(
        status=status,
        criterion=result.criterion_label,
        suspect_lines=suspects,
        crash_state=crash_state,
        slice_size=len(suspects),
        confidence=confidence,
        handoff_context=handoff,
        trace_path=trace_path,
        message=msg,
    )


def _has_recorded_exception(trace_path: str) -> bool:
    """Did the recorded run raise? Distinguishes a clean run from an unusable trace.

    Only consulted when slicing at the crash has already failed, so the extra
    reconstruction costs nothing on the normal path.
    """
    try:
        reverse_trace(trace_path, at_exception=True, step_back=0)
        return True
    except Exception:  # noqa: BLE001 — any failure here means "no usable exception"
        return False


def _line_of(criterion: str | None) -> int | None:
    """Extract LINE from a '[FILE:]LINE[:VAR]' criterion string."""
    if not criterion:
        return None
    parts = criterion.split(":")
    for p in parts:
        if p.strip().isdigit():
            return int(p.strip())
    return None
