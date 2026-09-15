"""KIO2 trace comparison — FR-KIO2-03, alignment across multiple runs.

Two traces of the same program produce a **distance** (how (dis)similar the runs
are, 0 for identical ones — the requirement's invariant) and an **alignment**
(how they line up, with divergences as gaps) — the requirement's two Outputs.
On top of that, a cursor on trace A reports the aligned point in trace B and the
variables whose recorded values differ there, which is the requirement's
Objective: *"manipulation of multiple execution traces within a single
interactive session"*.

Three or more traces are treated as a **set** (the requirement's Input, *"a set
of execution traces relating to a single program ran with the different inputs
and configurations"*): the pairwise distance matrix, the reference run (medoid)
and the outlier. That matrix is also what FR-KIO2-05 needs downstream to look
for statistical anomalies across a trace set.

The alignment engine lives in FocusTracer (``core/align.py``); this module maps
it onto the KIO contract. Read-only — no program is re-run.

Note on what the distance measures: traces are tokenised as the executed
``function:line`` sequence, so the distance compares **control flow**. Two runs
that take the same path with different data have distance 0; their difference
surfaces in ``delta`` (the per-variable value comparison at the aligned point).
"""

from __future__ import annotations

from focustracer.core.align import AlignedPair, TraceSet

from .contract import AlignInput, TraceComparison

_STEP_ACTIONS = ("into", "over", "out")


def compare(inp: AlignInput) -> TraceComparison:
    """Align ``inp.trace_paths``: pairwise (2) or as a curated set (3+)."""
    paths = [p for p in inp.trace_paths if p]
    if len(paths) < 2:
        return TraceComparison(
            status="FAILED", trace_paths=paths,
            message="Alignment needs at least two traces of the same program.",
            error="fewer than two traces given",
        )
    return _compare_set(inp, paths) if len(paths) > 2 else _compare_pair(inp, paths)


def _compare_pair(inp: AlignInput, paths: list[str]) -> TraceComparison:
    try:
        pair = AlignedPair(paths[0], paths[1])
        _seek(pair, inp)
    except FileNotFoundError as exc:
        return _failed(paths, "One of the traces was not found.", exc)
    except ValueError as exc:
        return _failed(paths, "Traces could not be aligned — check the start point and detail level.", exc)

    if inp.step > 0:
        pair.step_forward(inp.step)
    elif inp.step < 0:
        pair.step_back(-inp.step)
    if inp.step_action in _STEP_ACTIONS:
        pair.step(inp.step_action, back=inp.back)

    view = pair.to_dict(window=max(0, inp.window))
    al = pair.alignment
    identical = al.distance == 0
    where = "identical statement sequences" if identical else f"{al.gaps} divergent statement(s)"

    return TraceComparison(
        status="DONE",
        mode="pair",
        trace_paths=paths,
        distance=al.distance,
        normalized_distance=round(al.normalized_distance, 4),
        matched=al.matched,
        gaps=al.gaps,
        aligned=view["aligned"],
        a_seq=view["a_seq"],
        b_seq=view["b_seq"],
        a=view["a"],
        b=view["b"],
        delta=view["delta"],
        divergences=[d.to_dict() for d in al.divergences()],
        pairs=al.pairs if inp.include_pairs else None,
        message=f"Distance {al.distance} (normalized {al.normalized_distance:.3f}) — {where}.",
    )


def _compare_set(inp: AlignInput, paths: list[str]) -> TraceComparison:
    try:
        summary = TraceSet(paths).summary()
    except FileNotFoundError as exc:
        return _failed(paths, "One of the traces was not found.", exc)
    except ValueError as exc:
        return _failed(paths, "Trace set could not be built.", exc)

    d = summary.to_dict()
    ref, out = summary.reference, summary.outlier
    return TraceComparison(
        status="DONE",
        mode="set",
        trace_paths=list(summary.paths),
        lengths=summary.lengths,
        matrix=d["matrix"],
        reference=ref,
        outlier=out,
        mean_distance=d["mean_distance"],
        message=(
            f"{len(paths)} traces — reference #{ref}, outlier #{out} "
            f"(distance {summary.matrix[ref][out]:.3f}), "
            f"mean pairwise distance {summary.mean_distance:.3f}."
        ),
    )


def _seek(pair: AlignedPair, inp: AlignInput) -> None:
    pair.seek(
        seq=inp.seq, event=inp.at_event, line=inp.at_line,
        function=inp.function, at_exception=inp.at_exception,
    )


def _failed(paths: list[str], message: str, exc: Exception) -> TraceComparison:
    return TraceComparison(status="FAILED", trace_paths=paths, message=message, error=str(exc))
