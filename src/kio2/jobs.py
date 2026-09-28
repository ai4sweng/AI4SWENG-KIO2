"""KIO1 job contract: ``POST /jobs`` + ``GET /jobs/{job_id}``.

This is the contract KIO1's dispatcher speaks today (``kio10/transport.py`` in
the orchestrator, agreed in the *KIO1 – KIO10 Integration* document), which KIO1
applies unchanged to every agent it dispatches to:

    request   {schema_version, workflow_id, step_id, capability, task, data}
    ack       {schema_version, workflow_id, step_id, job_id, status: "accepted"}
    final     ... status: "success"  + artifacts {name: {schema_id, receipt: {uri}}}
              ... status: "failure"  + failure_class, diagnostics

``GET /jobs/{job_id}`` answers with the acknowledgement while the job runs, then
with the final reply. Like :mod:`kio2.kio1`, this is a **pure adapter**: it
translates the envelope into an :class:`~kio2.kio1.ExecutionMessage` and lets
:func:`kio2.kio1.handle` do the work, so both contracts share one implementation.

Two things differ from the synchronous ``/execute`` envelope:

- **Inputs are references.** KIO1 accepts only ``{uri, schema_id}`` objects in a
  plan's ``data``, and passes a finished dependency's artifacts on the same way.
  KIO2 therefore reads ``repository`` and ``entry_point`` as ``file://`` URIs,
  and every ``kio2://trace/`` URI as a recording to replay or compare.
- **The recording budget is the job budget.** Nothing waits synchronously, so a
  job may record for ``KIO2_JOB_TRACE_BUDGET`` seconds (default 180, KIO2's own
  contract) rather than the 45 seconds of ``/execute``. KIO1's step timeout
  (600 s by default) bounds the whole job.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import kio1

SCHEMA_VERSION = "1.0"

ACCEPTED = "accepted"
SUCCESS = "success"
FAILURE = "failure"

JOB_TRACE_BUDGET_SECONDS = float(os.environ.get("KIO2_JOB_TRACE_BUDGET", "180"))

#: Finished jobs are kept for polling; the oldest are dropped beyond this many.
MAX_JOBS = int(os.environ.get("KIO2_MAX_JOBS", "500"))

#: Artifact name per capability. A dependent step receives each artifact under
#: this name in its ``data``.
ARTIFACT_NAMES = {
    kio1.CAP_BUG_LOCALIZATION: "fault_localization",
    kio1.CAP_DIAGNOSIS: "diagnosis",
    kio1.CAP_REPLAY: "replay_view",
    kio1.CAP_TRACE_ALIGNMENT: "trace_comparison",
}

#: The recording, published as its own artifact so that a later replay or
#: alignment step receives it through KIO1's artifact passing.
TRACE_ARTIFACT = "trace"
TRACE_SCHEMA_ID = "kio2.trace/2.3"

#: A replay step dispatched by KIO1 cannot carry a cursor (plan ``data`` holds
#: references only), so it opens at the recorded failure unless one is given.
_CURSOR_KEYS = ("seq", "at_event", "at_line", "at_exception", "step", "step_action", "back")


class RequestError(ValueError):
    """The body is not a KIO1 job request; answered with HTTP 422."""


# ── request → ExecutionMessage ───────────────────────────────────────────────


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("uri"), str)


def _ref_uris(value: Any) -> list[str]:
    """URIs of a reference or a list of references; empty for anything else."""
    items = value if isinstance(value, list) else [value]
    return [item["uri"] for item in items if _is_ref(item)]


def uri_to_path(uri: str) -> str:
    """A filesystem path from a ``file://`` URI, or the value unchanged.

    ``file:///workspace/repo`` gives ``/workspace/repo``; on Windows
    ``file:///E:/code/repo`` gives ``E:/code/repo``. A bare path is accepted too,
    for callers that write one.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    path = unquote(parsed.path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":   # /E:/... on Windows
        path = path[1:]
    return path


def _entry_relative_to(entry: str, root: str) -> str:
    """The entry point relative to the repository root when it lies inside it."""
    if not root:
        return entry
    try:
        return Path(entry).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return entry


def execution_message(request: dict[str, Any]) -> kio1.ExecutionMessage:
    """Translate a KIO1 job request into the message :func:`kio1.handle` answers.

    Reads from ``data``:

    - ``repository`` (``file://`` URI) — the repository root;
    - ``entry_point`` (``file://`` URI) — the script to record;
    - ``reference_trace`` (``kio2://trace/`` URI) — a passing run for diagnosis;
    - every other ``kio2://trace/`` URI, in order — the recordings to replay or
      compare, whatever name the upstream artifact carried.

    Entries that are not references are passed through unchanged, so a direct
    caller can still use the field names of the ``/execute`` envelope.
    """
    raw = request.get("data") or {}
    if not isinstance(raw, dict):
        raise RequestError("data must be a JSON object")

    data: dict[str, Any] = {k: v for k, v in raw.items()
                            if not (_is_ref(v) or (isinstance(v, list) and _ref_uris(v)))}

    root = next(iter(_ref_uris(raw.get("repository"))), None)
    if root:
        data["repository"] = {"path": uri_to_path(root)}
    entry = next(iter(_ref_uris(raw.get("entry_point"))), None)
    if entry:
        data["target"] = {"entry_point": _entry_relative_to(uri_to_path(entry), uri_to_path(root or ""))}

    reference = next(iter(_ref_uris(raw.get("reference_trace"))), None)
    if reference:
        data["reference"] = {"trace_ref": reference}

    traces: list[str] = []
    for name, value in raw.items():
        if name == "reference_trace":
            continue
        for uri in _ref_uris(value):
            if uri.startswith(kio1.TRACE_REF_PREFIX) and uri not in traces:
                traces.append(uri)
    if traces and "trace_refs" not in data and "trace_ref" not in data:
        data["trace_refs"] = traces

    capability = str(request.get("capability") or "")
    if capability == kio1.CAP_REPLAY and not any(k in data for k in _CURSOR_KEYS):
        data["at_exception"] = True

    message = kio1.ExecutionMessage(
        workflow_id=str(request.get("workflow_id") or ""),
        step_id=str(request.get("step_id") or ""),
        capability=capability,
        task=str(request.get("task") or ""),
        data=data,
    )
    message._trace_budget = JOB_TRACE_BUDGET_SECONDS
    return message


# ── AgentReply → final reply ─────────────────────────────────────────────────


def envelope(request: dict[str, Any], job_id: str, status: str) -> dict[str, Any]:
    """The fields every acknowledgement and reply carries."""
    return {
        "schema_version": SCHEMA_VERSION,
        "workflow_id": request.get("workflow_id"),
        "step_id": request.get("step_id"),
        "job_id": job_id,
        "status": status,
    }


def _receipt(uri: str, content: Any) -> dict[str, Any]:
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    return {"uri": uri, "version": 1, "content_hash": f"sha256:{digest}"}


def failure_class(capability: str, error: str) -> str:
    """Classify a failure with the codes proposed in the integration document (Table 8).

    The adapter underneath reports failures as text; the classification is kept
    in this one function so that it can move to typed errors without touching
    the contract.
    """
    text = (error or "").lower()
    if not capability or capability not in ARTIFACT_NAMES:
        return "unsupported_capability"
    if "no entry point" in text:
        return "entry_point_missing"
    if "outside the trace directory" in text:
        return "trace_ref_refused"
    if "trace not found" in text or "no trace to replay" in text or "set data.trace_refs" in text:
        return "trace_unavailable"
    if "timed out" in text:
        return "deadline_exceeded"
    if "not found" in text or "no such file" in text or "does not exist" in text:
        return "artifact_unavailable"
    return "analysis_failed"


def final_reply(request: dict[str, Any], job_id: str, reply: kio1.AgentReply) -> dict[str, Any]:
    """The KIO1 final reply for a finished :func:`kio1.handle` call.

    On success the capability's output becomes one artifact, and the recording
    a second one (``trace``) whenever the output names one. The output is also
    carried inline under ``output``: KIO1 stores the whole reply in its dispatch
    report, so the findings are readable there without dereferencing a receipt.
    """
    capability = str(request.get("capability") or "")
    if reply.status != "ok":
        out = envelope(request, job_id, FAILURE)
        out["failure_class"] = failure_class(capability, reply.error or "")
        message = reply.error or ""
        if out["failure_class"] == "entry_point_missing":
            # The adapter's text names the /execute fields; a job caller sends references.
            message = ("no entry point in the request: pass data.repository and "
                       "data.entry_point as file:// references (" + message + ")")
        out["diagnostics"] = {"agent_id": kio1.AGENT_ID, "message": message}
        return out

    output = reply.output or {}
    name = ARTIFACT_NAMES[capability]
    artifacts: dict[str, Any] = {
        name: {
            "schema_id": f"kio2.{name}/1.0",
            "receipt": _receipt(f"kio2://jobs/{job_id}/{name}", output),
        }
    }
    trace_ref = output.get("trace_ref")
    if isinstance(trace_ref, str) and trace_ref.startswith(kio1.TRACE_REF_PREFIX):
        artifacts[TRACE_ARTIFACT] = {
            "schema_id": TRACE_SCHEMA_ID,
            "receipt": {"uri": trace_ref, "version": 1},
        }

    out = envelope(request, job_id, SUCCESS)
    out["artifacts"] = artifacts
    out["output"] = output
    return out


# ── job store ────────────────────────────────────────────────────────────────


@dataclass
class _Job:
    request: dict[str, Any]
    job_id: str
    final: dict[str, Any] | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


def validate_request(body: Any) -> dict[str, Any]:
    """Check the fields KIO1 matches replies on; raise :class:`RequestError` otherwise."""
    if not isinstance(body, dict):
        raise RequestError("the request must be a JSON object")
    version = body.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise RequestError(f"schema_version {version!r} is not supported; expected {SCHEMA_VERSION!r}")
    for key in ("workflow_id", "step_id"):
        if not isinstance(body.get(key), str) or not body[key]:
            raise RequestError(f"{key} must be a non-empty string")
    return body


class JobStore:
    """In-memory jobs of one KIO2 process.

    A resubmission of the same ``(workflow_id, step_id)`` returns the existing
    job rather than recording the program again, the repeat protection KIO1's
    contract asks of an agent. Jobs are not shared between processes: a
    replicated deployment has to route the polls of a job to the instance that
    accepted it, as it already has to for trace references.
    """

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._by_step: dict[tuple[str, str], str] = {}
        self._max_jobs = max_jobs

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        """Accept a validated request and start it; return the acknowledgement."""
        key = (request["workflow_id"], request["step_id"])
        job_id = self._by_step.get(key)
        if job_id is None or job_id not in self._jobs:
            job_id = f"kio2-job-{uuid.uuid4().hex[:12]}"
            job = _Job(request=request, job_id=job_id)
            self._jobs[job_id] = job
            self._by_step[key] = job_id
            job.task = asyncio.create_task(self._run(job))
            self._evict()
        return envelope(request, job_id, ACCEPTED)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """The acknowledgement while the job runs, its final reply after; None if unknown."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return job.final or envelope(job.request, job_id, ACCEPTED)

    async def _run(self, job: _Job) -> None:
        from .observability import task_span

        try:
            message = execution_message(job.request)
            with task_span(f"kio1.jobs.{message.capability or 'unknown'}",
                           message.workflow_id, message.step_id):
                reply = await asyncio.to_thread(kio1.handle, message)
        except Exception as exc:  # noqa: BLE001 — a job must always settle
            reply = kio1.AgentReply(status="error", error=f"{type(exc).__name__}: {exc}")
        job.final = final_reply(job.request, job.job_id, reply)

    def _evict(self) -> None:
        while len(self._jobs) > self._max_jobs:
            old_id, old = next(iter(self._jobs.items()))
            if old.final is None:        # never drop a running job
                break
            self._jobs.pop(old_id)
            self._by_step.pop((old.request["workflow_id"], old.request["step_id"]), None)

