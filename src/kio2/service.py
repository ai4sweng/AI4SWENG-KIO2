"""KIO2 service adapter — expose the localizer over the KIO contract.

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

from .contract import FaultLocalization, Kio2Input
from .localizer import localize
from .observability import localization_span

KIO_ID = "kio2"
TITLE = "Bug Locate & Fix: Reverse Execution & Dynamic Slicing"


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


async def kio2_handler(envelope: Any) -> dict[str, Any]:
    """KIO2 handler: envelope → fault localization → JOB_RESULT payload."""
    payload = getattr(envelope, "payload", {}) or {}
    session_id = getattr(envelope, "session_id", "")
    inp = _input_from_payload(payload)
    with localization_span(session_id, inp.target_script) as ctx:
        result = await asyncio.to_thread(localize, inp)
        ctx["result"] = result
    return _to_kio_result(result)


# ── App factory ───────────────────────────────────────────────────────────────

_SUPPORTED_TASKS = [
    {
        "task_type": "fault_localization",
        "description": "Locate the fault behind a failing execution via dynamic slicing.",
        "input_schema": "kio2_input_v1",
        "output_schema": "fault_localization_v1",
    }
]


def make_app(kio_id: str = KIO_ID, title: str = TITLE):
    """Return a FastAPI app for KIO2 (platform shell if available, else standalone)."""
    try:
        from kio_base import make_kio_app  # type: ignore[import]

        return make_kio_app(kio_id, title, kio2_handler, supported_tasks=_SUPPORTED_TASKS)
    except Exception:
        return _standalone_app(kio_id, title)


def _standalone_app(kio_id: str, title: str):
    """Minimal FastAPI app mirroring the KIO /execute contract (no platform deps)."""
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title=f"{kio_id.upper()} — {title}", version="0.1.0")

    class _Envelope(BaseModel):
        session_id: str = ""
        payload: dict[str, Any] = {}

    @app.get("/health/")
    async def health() -> dict[str, Any]:
        from .observability import otel_enabled
        return {"status": "ok", "service": kio_id, "title": title, "otel": otel_enabled()}

    @app.post("/execute")
    async def execute(body: _Envelope) -> dict[str, Any]:
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
