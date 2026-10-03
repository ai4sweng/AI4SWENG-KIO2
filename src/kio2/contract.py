"""KIO2 input/output contract (D2.6 — Bug Locate & Fix).

These Pydantic models define the interface KIO2 exposes to the orchestrator
and to neighbouring KIOs. They are transport-agnostic: the same models are
used whether KIO2 runs inside the AI4SWENG platform (via ``make_kio_app``),
in the standalone KIO2 repository, or as a plain library call.

KIO2 scope per D2.6: locate the fault (reverse execution + dynamic slicing).
It does NOT generate the fix — that is KIO7. The ``handoff_context`` field is
the packaged slice KIO2 hands to KIO7.

Three task families, one per requirement:

===========================  ================================  ==============
Task type                    Input / Output                    Requirement
===========================  ================================  ==============
``fault_localization``       ``Kio2Input`` → ``FaultLocalization``   FR-KIO2-05
``replay``                   ``ReplayInput`` → ``ReplayView``        FR-KIO2-02
``trace_alignment``          ``AlignInput`` → ``TraceComparison``    FR-KIO2-03
===========================  ================================  ==============
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Kio2Input(BaseModel):
    """What KIO2 needs to localise a fault.

    Normally the failing execution (repo + failing test) arrives from upstream
    KIOs (e.g. KIO11 test automation). Until those are wired, a dummy input
    supplies the same fields.
    """

    target_script: str = Field(..., description="Path to the failing script / entrypoint to trace")
    working_directory: str = Field("", description="Repo root; used as cwd and project root")
    functions: list[str] = Field(default_factory=list, description="Trace targets; empty ⇒ trace all")
    criterion: str | None = Field(None, description="[FILE:]LINE[:VAR]; None ⇒ localise at the crash")
    failing_test: str | None = Field(None, description="Failing test / error context from upstream (optional)")
    detail: str = Field("detailed", description="Trace detail level (needs 'detailed' for slicing)")
    schema_version: str = Field("2.3", description="Trace schema (slicing needs >= 2.3)")
    trace_timeout: float | None = Field(
        None,
        description="Seconds to allow for recording; None uses the runner default. "
                    "Callers with their own deadline (KIO1 waits 60 s) should set it lower.",
    )

    def to_payload(self) -> dict[str, Any]:
        return _dump(self)


class SuspectLine(BaseModel):
    """One statement implicated in the fault, with its evidence and score."""

    rank: int
    score: float
    dependency: str  # "criterion" | "control" | "data"
    file: str
    function: str
    line: int
    source: str


class FaultLocalization(BaseModel):
    """KIO2's output: ranked suspect statements + evidence, ready for HITL/KIO7."""

    status: str  # "DONE" | "REVIEW_REQUIRED" | "FAILED"
    criterion: str = ""
    suspect_lines: list[SuspectLine] = Field(default_factory=list)
    crash_state: dict[str, Any] = Field(default_factory=dict)
    slice_size: int = 0
    confidence: float = 0.0
    handoff_context: str = ""  # slice context for KIO7 (fix generation)
    trace_path: str = ""
    message: str = ""
    error: str | None = None

    def to_artifact(self) -> dict[str, Any]:
        return _dump(self)


# ── FR-KIO2-02: replay ────────────────────────────────────────────────────────


class ReplayInput(BaseModel):
    """Where to place the replay cursor in an already-recorded trace.

    The start point is one of ``seq`` / ``at_event`` / ``at_line`` /
    ``at_exception`` (default: the start of execution); ``step`` and
    ``step_action`` then move from there. Stateless by design: a UI keeps the
    returned ``cursor`` and sends it back as ``seq`` on the next call.
    """

    trace_path: str = Field(..., description="Path to a recorded trace XML")
    seq: int | None = Field(None, description="Start at timeline index")
    at_event: int | None = Field(None, description="Start at line-event id")
    at_line: int | None = Field(None, description="Start at a source line")
    function: str | None = Field(None, description="Disambiguate at_line by function")
    at_exception: bool = Field(False, description="Start at the recorded crash")
    step: int = Field(0, description="Signed line steps from the start point (+fwd / -back)")
    step_action: str | None = Field(None, description="Debugger step: 'into' | 'over' | 'out'")
    back: bool = Field(False, description="Apply step_action backward (reverse execution)")
    window: int = Field(3, description="Neighbour line-events to return around the cursor")
    def_var: str | None = Field(None, description="Report the statement that last defined this variable")

    def to_payload(self) -> dict[str, Any]:
        return _dump(self)


class ReplayView(BaseModel):
    """The cursor position, the state recorded there, and its neighbourhood."""

    status: str  # "DONE" | "FAILED"
    trace_path: str = ""
    cursor: int = 0
    total: int = 0
    can_forward: bool = False
    can_back: bool = False
    current: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    def_of: dict[str, Any] | None = None
    message: str = ""
    error: str | None = None

    def to_artifact(self) -> dict[str, Any]:
        return _dump(self)


# ── FR-KIO2-03: trace alignment ───────────────────────────────────────────────


class AlignInput(BaseModel):
    """Two traces to align (optionally navigated side by side), or N to curate.

    Two paths ⇒ ``mode="pair"``: distance, divergence regions, and a cursor on
    trace A reporting the aligned point and value deltas in trace B. Three or
    more ⇒ ``mode="set"``: the pairwise distance matrix plus the reference
    (medoid) and outlier of the set.
    """

    trace_paths: list[str] = Field(..., description="Traces of the same program (>= 2)")
    seq: int | None = Field(None, description="Place A's cursor at this timeline index")
    at_event: int | None = Field(None, description="Place A's cursor at a line-event id")
    at_line: int | None = Field(None, description="Place A's cursor at a source line")
    function: str | None = Field(None, description="Disambiguate at_line by function")
    at_exception: bool = Field(False, description="Place A's cursor at the crash")
    step: int = Field(0, description="Signed line steps from the start point")
    step_action: str | None = Field(None, description="Debugger step on A: 'into' | 'over' | 'out'")
    back: bool = Field(False, description="Apply step_action backward")
    window: int = Field(3, description="Neighbour line-events around each cursor")
    include_pairs: bool = Field(False, description="Include the raw alignment pair list (large)")

    def to_payload(self) -> dict[str, Any]:
        return _dump(self)


class TraceComparison(BaseModel):
    """How a set of traces relate: distance, alignment, and where they diverge."""

    status: str  # "DONE" | "FAILED"
    mode: str = ""  # "pair" | "set"
    trace_paths: list[str] = Field(default_factory=list)

    # mode="pair"
    distance: int = 0
    normalized_distance: float = 0.0
    matched: int = 0
    gaps: int = 0
    aligned: bool = False
    a_seq: int = 0
    b_seq: int | None = None
    a: dict[str, Any] = Field(default_factory=dict)
    b: dict[str, Any] | None = None
    delta: list[dict[str, Any]] = Field(default_factory=list)
    divergences: list[dict[str, Any]] = Field(default_factory=list)
    pairs: list[Any] | None = None

    # mode="set"
    lengths: list[int] = Field(default_factory=list)
    matrix: list[list[float]] = Field(default_factory=list)
    reference: int | None = None
    outlier: int | None = None
    mean_distance: float = 0.0

    message: str = ""
    error: str | None = None

    def to_artifact(self) -> dict[str, Any]:
        return _dump(self)


def _dump(model: BaseModel) -> dict[str, Any]:
    """Pydantic v2/v1 compatible serialisation."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()  # type: ignore[attr-defined]
