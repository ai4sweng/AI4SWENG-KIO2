"""KIO2 service adapter — expose KIO2's capabilities over the KIO contract.

Three task types share one ``/execute`` endpoint, selected by ``task_type`` in
the payload (or inferred from its shape when omitted):

- ``fault_localization`` — record, slice, rank suspects (FR-KIO2-05);
- ``replay`` — post-mortem navigation over a recorded trace (FR-KIO2-02);
- ``trace_alignment`` — compare runs / curate a trace set (FR-KIO2-03).

Two deployment modes, one handler:

- **Platform**: if the AI4SWENG ``kio_base`` module is importable (KIO2 dropped
  into ``apps/kio_shells/``), ``make_app`` builds the real KIO shell via
  ``make_kio_app`` — HTTP ``/execute`` + NATS, HITL, capability announcements.
- **Standalone**: otherwise ``make_app`` returns a minimal FastAPI app with the
  same ``/execute`` contract, so KIO2 runs in its own repo unchanged.

The handler itself is transport-agnostic: it reads ``envelope.payload`` and
``envelope.session_id`` and returns the KIO JOB_RESULT dict.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel, Field

from .comparator import compare
from .contract import AlignInput, FaultLocalization, Kio2Input, ReplayInput
from .localizer import localize
from .observability import localization_span, task_span
from .replayer import replay

KIO_ID = "kio2"
TITLE = "Bug Locate & Fix: Reverse Execution & Dynamic Slicing"

TASK_LOCALIZE = "fault_localization"   # FR-KIO2-05 (via dynamic slicing)
TASK_REPLAY = "replay"                 # FR-KIO2-02
TASK_ALIGN = "trace_alignment"         # FR-KIO2-03


def _task_of(payload: dict[str, Any]) -> str:
    """Which task the envelope asks for.

    Explicit ``task_type`` wins. Otherwise it is inferred from the payload shape,
    so existing callers that only ever sent a localization payload keep working
    unchanged: ``trace_paths`` ⇒ alignment, ``trace_path`` ⇒ replay, else localize.
    """
    declared = (payload.get("task_type") or "").strip()
    if declared:
        return declared
    if payload.get("trace_paths"):
        return TASK_ALIGN
    if payload.get("trace_path"):
        return TASK_REPLAY
    return TASK_LOCALIZE


def _input_from_payload(payload: dict[str, Any]) -> Kio2Input:
    """Build a Kio2Input from an envelope payload; fall back to the dummy example."""
    if not payload.get("target_script"):
        from .dummy import dummy_input
        return dummy_input()
    return Kio2Input(
        target_script=payload["target_script"],
        working_directory=payload.get("working_directory", ""),
        functions=payload.get("functions", []) or [],
        criterion=payload.get("criterion"),
        failing_test=payload.get("failing_test"),
        detail=payload.get("detail", "detailed"),
        schema_version=payload.get("schema_version", "2.3"),
    )


def _to_kio_result(result: FaultLocalization) -> dict[str, Any]:
    """Map a FaultLocalization onto the KIO JOB_RESULT payload contract."""
    artifact = {
        "status": result.status if result.status != "REVIEW_REQUIRED" else "REVIEW_REQUIRED",
        "artifact_id": str(uuid.uuid4()),
        "artifact_data": {"kio": KIO_ID, **result.to_artifact()},
        "message": result.message,
    }
    if result.status == "FAILED":
        artifact["status"] = "FAILED"
        artifact["error"] = {
            "error_code": "KIO2_LOCALIZATION_FAILED",
            "error_message": result.error or result.message,
            "retryable": False,
        }
    elif result.status == "REVIEW_REQUIRED":
        top = result.suspect_lines[0] if result.suspect_lines else None
        where = f"{top.function} L{top.line}" if top else "unknown"
        artifact["hitl_question"] = (
            f"KIO2 localised the fault to {where} with confidence {result.confidence}. "
            "Review the suspect statements before handing off to KIO7 for a fix?"
        )
    return artifact


def _known_fields(model_cls: type) -> set[str]:
    """Field names of a Pydantic model (v2 ``model_fields``, v1 ``__fields__``)."""
    fields = getattr(model_cls, "model_fields", None) or getattr(model_cls, "__fields__", {})
    return set(fields)


def _artifact(result: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wrap any KIO2 result model in the KIO JOB_RESULT envelope."""
    out = {
        "status": result.status,
        "artifact_id": str(uuid.uuid4()),
        "artifact_data": {"kio": KIO_ID, **result.to_artifact(), **(extra or {})},
        "message": result.message,
    }
    if result.status == "FAILED":
        out["error"] = {
            "error_code": f"KIO2_{(extra or {}).get('task_type', 'TASK').upper()}_FAILED",
            "error_message": result.error or result.message,
            "retryable": False,
        }
    return out


async def _handle_replay(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """FR-KIO2-02 — post-mortem navigation over a recorded trace."""
    inp = ReplayInput(**{k: v for k, v in payload.items() if k in _known_fields(ReplayInput)})
    with task_span(TASK_REPLAY, session_id, inp.trace_path) as ctx:
        result = await asyncio.to_thread(replay, inp)
        ctx["result"] = result
    return _artifact(result, {"task_type": TASK_REPLAY})


async def _handle_align(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """FR-KIO2-03 — align two traces side by side, or curate a set of them."""
    inp = AlignInput(**{k: v for k, v in payload.items() if k in _known_fields(AlignInput)})
    target = ", ".join(inp.trace_paths[:2])
    with task_span(TASK_ALIGN, session_id, target) as ctx:
        result = await asyncio.to_thread(compare, inp)
        ctx["result"] = result
    return _artifact(result, {"task_type": TASK_ALIGN})


async def _handle_localize(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """FR-KIO2-05 — locate the fault behind a failing execution."""
    inp = _input_from_payload(payload)
    with localization_span(session_id, inp.target_script) as ctx:
        result = await asyncio.to_thread(localize, inp)
        ctx["result"] = result
    return _to_kio_result(result)


async def kio2_handler(envelope: Any) -> dict[str, Any]:
    """KIO2 handler: envelope → the requested task's artifact → JOB_RESULT payload."""
    payload = getattr(envelope, "payload", {}) or {}
    session_id = getattr(envelope, "session_id", "")
    task = _task_of(payload)

    if task == TASK_REPLAY:
        return await _handle_replay(payload, session_id)
    if task == TASK_ALIGN:
        return await _handle_align(payload, session_id)
    if task == TASK_LOCALIZE:
        return await _handle_localize(payload, session_id)

    return {
        "status": "FAILED",
        "artifact_id": str(uuid.uuid4()),
        "artifact_data": {"kio": KIO_ID, "task_type": task},
        "message": f"Unknown task_type '{task}'.",
        "error": {
            "error_code": "KIO2_UNKNOWN_TASK",
            "error_message": (
                f"'{task}' is not supported. Known tasks: "
                f"{TASK_LOCALIZE}, {TASK_REPLAY}, {TASK_ALIGN}."
            ),
            "retryable": False,
        },
    }


# ── App factory ───────────────────────────────────────────────────────────────

_SUPPORTED_TASKS = [
    {
        "task_type": TASK_LOCALIZE,
        "description": "Locate the fault behind a failing execution via dynamic slicing.",
        "input_schema": "kio2_input_v1",
        "output_schema": "fault_localization_v1",
    },
    {
        "task_type": TASK_REPLAY,
        "description": (
            "Post-mortem navigation over a recorded trace: step into/over/out, "
            "forward and backward, inspect recorded state and def-use (FR-KIO2-02)."
        ),
        "input_schema": "kio2_replay_v1",
        "output_schema": "replay_view_v1",
    },
    {
        "task_type": TASK_ALIGN,
        "description": (
            "Align execution traces of the same program: distance, divergences and "
            "side-by-side state for two traces, or distance matrix, reference and "
            "outlier for a trace set (FR-KIO2-03)."
        ),
        "input_schema": "kio2_align_v1",
        "output_schema": "trace_comparison_v1",
    },
]


def make_app(kio_id: str = KIO_ID, title: str = TITLE):
    """Return a FastAPI app for KIO2 (platform shell if available, else standalone)."""
    try:
        from kio_base import make_kio_app  # type: ignore[import]

        return make_kio_app(kio_id, title, kio2_handler, supported_tasks=_SUPPORTED_TASKS)
    except Exception:
        return _standalone_app(kio_id, title)


class JobRequest(BaseModel):
    """The KIO JOB_REQUEST envelope accepted by the standalone ``/execute``.

    Defined at module level on purpose: this module uses ``from __future__ import
    annotations``, so FastAPI resolves the handler's annotations as *strings*
    against the module globals. A model nested inside the factory is invisible
    there, and FastAPI silently degrades the parameter to a query field —
    every POST then fails with 422 before the handler is ever reached.
    """

    session_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def _standalone_app(kio_id: str, title: str):
    """Minimal FastAPI app mirroring the KIO /execute contract (no platform deps)."""
    from fastapi import FastAPI

    app = FastAPI(title=f"{kio_id.upper()} — {title}", version="1.0.6")

    @app.get("/health/")
    async def health() -> dict[str, Any]:
        from .observability import otel_enabled
        return {"status": "ok", "service": kio_id, "title": title, "otel": otel_enabled()}

    @app.get("/tasks")
    async def tasks() -> dict[str, Any]:
        """Capability discovery — the same list the platform shell announces."""
        return {"service": kio_id, "supported_tasks": _SUPPORTED_TASKS}

    @app.post("/execute")
    async def execute(body: JobRequest) -> dict[str, Any]:
        # Accept either {session_id, payload} or a bare payload dict.
        payload = body.payload or {}
        env = type("E", (), {"payload": payload, "session_id": body.session_id})()
        result_payload = await kio2_handler(env)
        return {
            "message_id": str(uuid.uuid4()),
            "session_id": body.session_id,
            "source": kio_id,
            "message_type": "JOB_RESULT",
            "payload": result_payload,
        }

    return app


app = make_app()
