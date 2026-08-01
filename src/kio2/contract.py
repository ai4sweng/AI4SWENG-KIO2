"""KIO2 input/output contract (D2.6 — Bug Locate & Fix).

These Pydantic models define the interface KIO2 exposes to the orchestrator
and to neighbouring KIOs. They are transport-agnostic: the same models are
used whether KIO2 runs inside the AI4SWENG platform (via ``make_kio_app``),
in the standalone KIO2 repository, or as a plain library call.

KIO2 scope per D2.6: locate the fault (reverse execution + dynamic slicing).
It does NOT generate the fix — that is KIO7. The ``handoff_context`` field is
the packaged slice KIO2 hands to KIO7.
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


def _dump(model: BaseModel) -> dict[str, Any]:
    """Pydantic v2/v1 compatible serialisation."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()  # type: ignore[attr-defined]
