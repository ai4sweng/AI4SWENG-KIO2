"""KIO1 dispatch protocol adapter.

KIO1 speaks its own envelope — the *KIO1 – KIO10 Integration Strategy and
Communication Protocol* — which is not the ``{session_id, payload}`` shape KIO2's
own contract uses:

    request   {workflow_id, step_id, agent_id, capability, endpoint, task, data}
    reply     {workflow_id, step_id, agent_id, status, output, error}

This module translates between the two. It is a **pure adapter**: the domain
logic stays in ``localizer`` / ``replayer`` / ``comparator``, which know nothing
about KIO1. Both envelopes are served on the same ``/execute`` path (that is what
KIO1's ``config.json`` registers), told apart by the shape of the body.

Three rules from KIO1's side that shape the code here:

- **Always answer HTTP 200.** A non-2xx status means *"your service is broken"*,
  which is a different thing from *"the task failed"*. A failed task is
  ``status: "error"`` inside a 200 response.
- **``status`` is assumed to be ``"ok"`` when absent.** So every reply sets it
  explicitly; a silently missing field would be read as a success with no output.
- **``output`` shape is ours to define.** KIO1 stores it verbatim and passes it to
  dependent steps as ``data.upstream.<step_id>``. Shapes below follow KIO1's own
  reference stub (``summary`` + ``findings``) so its prompt and UI see what they
  expect.

Also enforced here: a recording budget below KIO1's 60-second dispatch timeout,
so KIO2 answers rather than being abandoned mid-trace.
"""

from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .comparator import compare
from .contract import AlignInput, FaultLocalization, Kio2Input, ReplayInput
from .localizer import localize
from .replayer import replay

AGENT_ID = "KIO2"

# ── capabilities ─────────────────────────────────────────────────────────────

CAP_BUG_LOCALIZATION = "bug_localization"
CAP_DIAGNOSIS = "diagnosis"
CAP_REPLAY = "replay"
CAP_TRACE_ALIGNMENT = "trace_alignment"
CAP_FIX_RECOMMENDATION = "fix_recommendation"

#: What KIO2 answers for. Register exactly these in KIO1's `config.json`;
#: KIO1 skips a step whose capability an agent did not declare.
CAPABILITIES: list[str] = [
    CAP_BUG_LOCALIZATION,
    CAP_DIAGNOSIS,
    CAP_REPLAY,
    CAP_TRACE_ALIGNMENT,
]

#: Declared by KIO1 for KIO2 today, but out of KIO2's D2.6 scope: UC-UC1-03 makes
#: fix generation KIO7's step. Answered with an explicit error rather than a
#: plausible-looking guess, so the mismatch surfaces instead of hiding.
UNSUPPORTED_CAPABILITIES: dict[str, str] = {
    CAP_FIX_RECOMMENDATION: (
        "KIO2 localises faults; it does not generate fixes. Per D2.6 UC-UC1-03 the "
        "fix patch is KIO7's step, and KIO2 supplies the evidence for it: run "
        f"'{CAP_DIAGNOSIS}' here and pass its 'slice_context' to KIO7. Remove "
        f"'{CAP_FIX_RECOMMENDATION}' from KIO2's capabilities in KIO1's config, or "
        "raise the D2.6 role inconsistency with the consortium (see docs/INTEGRATION.md)."
    ),
}

#: KIO1 waits `dispatch.request_timeout` (60 s by default) and does not retry, so
#: recording has to finish inside that window with room for slicing and the reply.
#: Overridable for deployments that raised KIO1's timeout.
TRACE_BUDGET_SECONDS = float(os.environ.get("KIO2_TRACE_BUDGET", "45"))

#: Traces may only be read from under here. KIO1 is internal, but the adapter is
#: still the network edge: without this, a crafted `trace_ref` could make KIO2
#: parse an arbitrary file and return its contents as "recorded state".
TRACE_ROOT = Path(os.environ.get("KIO2_TRACE_DIR") or tempfile.gettempdir()).resolve()

TRACE_REF_PREFIX = "kio2://trace/"


# ── the KIO1 envelope ────────────────────────────────────────────────────────


class ExecutionMessage(BaseModel):
    """What KIO1 posts. Field names follow the integration protocol exactly."""

    workflow_id: str = ""
    step_id: str = ""
    agent_id: str = AGENT_ID
    capability: str = ""
    endpoint: str = ""
    task: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class AgentReply(BaseModel):
    """What KIO1 reads back. ``workflow_id`` / ``step_id`` are how it matches steps."""

    workflow_id: str = ""
    step_id: str = ""
    agent_id: str = AGENT_ID
    status: str = "ok"          # "ok" | "error"
    output: dict[str, Any] | None = None
    error: str | None = None


def is_kio1_message(body: dict[str, Any]) -> bool:
    """True when a request body is a KIO1 execution message.

    Any protocol field is enough. Deliberately generous: a KIO1 message that is
    missing ``capability`` must be recognised and answered with a real error,
    not fall through to the other envelope and quietly localise the dummy example.
    """
    return any(k in body for k in ("workflow_id", "step_id", "capability", "task", "endpoint"))


# ── trace references ─────────────────────────────────────────────────────────


def make_trace_ref(path: str) -> str:
    """A portable handle for a recorded trace.

    An absolute filesystem path is the wrong thing to hand across a service
    boundary, so the path is encoded instead. Stateless on purpose: any KIO2
    replica that can see the same trace directory resolves the same ref, which an
    in-memory registry could not do.
    """
    token = base64.urlsafe_b64encode(str(Path(path).resolve()).encode("utf-8")).decode("ascii")
    return TRACE_REF_PREFIX + token.rstrip("=")


def resolve_trace_ref(ref: str) -> str:
    """Turn a ``trace_ref`` (or a bare path) back into a readable trace file.

    Raises:
        ValueError: if the reference is malformed, escapes ``TRACE_ROOT``, or
            does not point at an existing ``.xml`` file.
    """
    if not ref:
        raise ValueError("no trace reference given")

    if ref.startswith(TRACE_REF_PREFIX):
        token = ref[len(TRACE_REF_PREFIX):]
        padding = "=" * (-len(token) % 4)
        try:
            candidate = base64.urlsafe_b64decode(token + padding).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"malformed trace reference: {ref}") from exc
    else:
        candidate = ref  # a bare path, for local callers

    path = Path(candidate).resolve()
    if not path.is_relative_to(TRACE_ROOT):
        raise ValueError(
            f"trace reference points outside the trace directory ({TRACE_ROOT}); refused"
        )
    if path.suffix.lower() != ".xml" or not path.is_file():
        raise ValueError(f"trace not found: {candidate}")
    return str(path)


# ── request → KIO2 input ─────────────────────────────────────────────────────


def _first(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None


def _upstream_values(data: dict[str, Any], key: str) -> Any:
    """Look for ``key`` in the outputs of the steps this one depends on.

    KIO1 delivers a step's dependencies as ``data.upstream.<step_id>``. A KIO11
    step that resolved the entry point, or an earlier KIO2 step that produced a
    trace, will have put it there.
    """
    upstream = data.get("upstream")
    if not isinstance(upstream, dict):
        return None
    for output in upstream.values():
        if not isinstance(output, dict):
            continue
        if output.get(key):
            return output[key]
        for nested in ("target", "repository", "failure"):
            block = output.get(nested)
            if isinstance(block, dict) and block.get(key):
                return block[key]
    return None


def _failure_context(data: dict[str, Any]) -> str | None:
    """Compact free-text description of the failure, for the record."""
    failure = data.get("failure")
    if not isinstance(failure, dict):
        failure = {}
    parts = [
        failure.get("test_id") or failure.get("test") or _upstream_values(data, "test_id"),
        failure.get("exception_type"),
        failure.get("message"),
    ]
    text = " — ".join(str(p) for p in parts if p)
    return text or None


def localization_input(message: ExecutionMessage) -> Kio2Input:
    """Build a ``Kio2Input`` from a KIO1 execution message.

    Raises:
        ValueError: when no entry point can be determined. KIO2 needs a *runnable*
            entry point; D2.6 specifies the input as failing test results, and
            nothing in the platform maps one to the other yet (INTEGRATION.md §5).
    """
    data = message.data or {}
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    repository = data.get("repository") if isinstance(data.get("repository"), dict) else {}

    entry = _first(
        target.get("entry_point"), target.get("target_script"),
        data.get("entry_point"), data.get("target_script"),
        _upstream_values(data, "entry_point"), _upstream_values(data, "target_script"),
    )
    if not entry:
        raise ValueError(
            "no entry point in the message. KIO2 records a real execution, so it needs a "
            "runnable script: set data.target.entry_point (and data.repository.path). "
            "A test id alone is not enough — see docs/INTEGRATION.md §7."
        )

    functions = _first(target.get("functions"), data.get("functions")) or []
    if not isinstance(functions, list):
        functions = []

    return Kio2Input(
        target_script=str(entry),
        working_directory=str(_first(repository.get("path"), data.get("working_directory")) or ""),
        functions=[str(f) for f in functions],
        criterion=data.get("criterion") or None,
        failing_test=_first(_failure_context(data), message.task) or None,
        trace_timeout=TRACE_BUDGET_SECONDS,
    )


def _nav_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Cursor controls shared by the replay and alignment capabilities."""
    keys = ("seq", "at_event", "at_line", "function", "at_exception",
            "step", "step_action", "back", "window")
    return {k: data[k] for k in keys if k in data and data[k] is not None}


def _trace_refs(data: dict[str, Any]) -> list[str]:
    """Every trace the caller pointed at, in order, refs or bare paths alike.

    An explicit list wins and is taken **verbatim** — no de-duplication, because
    comparing a trace with itself is a legitimate request (the distance-zero
    sanity check) and silently collapsing it would answer a different question.
    Singular keys and an inherited upstream ref are fallbacks, consulted only
    when no list was given.
    """
    for key in ("trace_refs", "trace_paths"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return [str(v) for v in value if v]

    for key in ("trace_ref", "trace_path"):
        value = data.get(key)
        if value:
            return [str(value)]

    inherited = _upstream_values(data, "trace_ref")
    return [str(inherited)] if inherited else []


# ── KIO2 result → KIO1 output ────────────────────────────────────────────────


def _relative(path: str, root: str) -> str:
    """Report a source file relative to the repo root.

    The recording holds absolute paths from inside KIO2's container. Those are
    meaningless to KIO1 and leak our filesystem layout, so everything crossing
    the boundary is reported the way the caller named its own repository.
    """
    if not path:
        return path
    if not root:
        return Path(path).name
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def _findings(result: FaultLocalization, root: str = "") -> list[dict[str, Any]]:
    """Suspect statements in the shape KIO1's reference stub returns.

    Per-finding ``confidence`` combines the run's overall confidence with the
    statement's evidence weight (``criterion`` 1.0 > ``control`` 0.75 > ``data``
    0.5), so the top finding carries the run's confidence and weaker evidence
    scores proportionally lower. ``score`` and ``dependency`` are kept alongside
    so a consumer can reason about the evidence itself.
    """
    return [
        {
            "file": _relative(s.file, root),
            "function": s.function,
            "line": s.line,
            "confidence": round(result.confidence * s.score, 3),
            "score": s.score,
            "dependency": s.dependency,
            "description": s.source,
        }
        for s in result.suspect_lines
    ]


def _flat_state(state: dict[str, Any]) -> dict[str, Any]:
    """``{name: {value, type}}`` → ``{name: value}`` for a compact output."""
    out: dict[str, Any] = {}
    for name, entry in (state or {}).items():
        out[name] = entry.get("value") if isinstance(entry, dict) else entry
    return out


def localization_output(result: FaultLocalization, root: str = "") -> dict[str, Any]:
    """`bug_localization` output: where the fault is, with runtime evidence."""
    top = result.suspect_lines[0] if result.suspect_lines else None
    where = (
        f"{_relative(top.file, root)}:{top.line} ({top.function})"
        if top else "an unidentified statement"
    )
    return {
        "summary": f"Located the fault at {where}.",
        "findings": _findings(result, root),
        "crash_state": _flat_state(result.crash_state),
        "criterion": result.criterion,
        "slice_size": result.slice_size,
        "confidence": result.confidence,
        "trace_ref": make_trace_ref(result.trace_path) if result.trace_path else None,
        "hitl_required": result.status == "REVIEW_REQUIRED",
    }


def _root_cause(result: FaultLocalization, root: str = "") -> str:
    """A factual causal statement — read off the slice, not inferred by a model.

    KIO2 is not the LLM in this pipeline; this describes what the recording
    actually shows: the statement that failed, the values it held, and the
    statements that produced those values.
    """
    if not result.suspect_lines:
        return "No statement could be implicated from the recording."
    top = result.suspect_lines[0]
    state = _flat_state(result.crash_state)
    values = ", ".join(f"{k}={v}" for k, v in list(state.items())[:6]) or "no locals recorded"
    feeders = [s for s in result.suspect_lines[1:] if s.dependency == "data"][:3]
    chain = "; ".join(f"{s.function}:{s.line} {s.source}" for s in feeders)
    text = (
        f"{top.function} at {_relative(top.file, root)}:{top.line} failed executing `{top.source}`, "
        f"with {values} in scope."
    )
    if chain:
        text += f" Those values are produced by: {chain}."
    return text


def diagnosis_output(
    result: FaultLocalization,
    comparison: dict[str, Any] | None = None,
    root: str = "",
) -> dict[str, Any]:
    """`diagnosis` output: the causal story plus the evidence behind it."""
    evidence: list[dict[str, Any]] = []
    top = result.suspect_lines[0] if result.suspect_lines else None
    for name, value in _flat_state(result.crash_state).items():
        evidence.append({
            "kind": "recorded_value",
            "at": f"{_relative(top.file, root)}:{top.line}" if top else "",
            "detail": f"{name} = {value}",
        })
    compared_runs = 1
    if comparison:
        compared_runs = 2
        for region in comparison.get("divergences", [])[:5]:
            evidence.append({
                "kind": "divergence",
                "detail": (
                    f"{region['length']} statement(s) ran only in "
                    f"{'this run' if region['side'] == 'a' else 'the reference run'}"
                ),
            })
        for delta in comparison.get("delta", [])[:10]:
            evidence.append({
                "kind": "value_difference",
                "detail": f"{delta['name']}: {delta['a']} here vs {delta['b']} in the reference run",
            })

    return {
        "summary": result.message.split("  [")[0],
        "root_cause": _root_cause(result, root),
        "evidence": evidence,
        "compared_runs": compared_runs,
        "slice_context": result.handoff_context,   # this is what KIO7 needs
        "confidence": result.confidence,
        "trace_ref": make_trace_ref(result.trace_path) if result.trace_path else None,
        "hitl_required": result.status == "REVIEW_REQUIRED",
    }


# ── capability handlers ──────────────────────────────────────────────────────


def _run_localization(message: ExecutionMessage) -> tuple[FaultLocalization, str | None, str]:
    inp = localization_input(message)
    result = localize(inp)
    return result, (result.error if result.status == "FAILED" else None), inp.working_directory


def _handle_bug_localization(message: ExecutionMessage) -> dict[str, Any]:
    result, failure, root = _run_localization(message)
    if failure:
        raise _TaskFailed(f"{result.message} {failure}".strip())
    return localization_output(result, root)


def _handle_diagnosis(message: ExecutionMessage) -> dict[str, Any]:
    result, failure, root = _run_localization(message)
    if failure:
        raise _TaskFailed(f"{result.message} {failure}".strip())

    # A reference run (typically a passing one) turns "where it broke" into
    # "how this run differed" — the strongest evidence we can offer.
    comparison = None
    data = message.data or {}
    reference = data.get("reference") if isinstance(data.get("reference"), dict) else {}
    ref = _first(reference.get("trace_ref"), reference.get("trace_path"),
                 data.get("reference_trace_ref"))
    if ref and result.trace_path:
        try:
            compared = compare(AlignInput(
                trace_paths=[result.trace_path, resolve_trace_ref(str(ref))],
                at_exception=True,
            ))
            if compared.status == "DONE":
                comparison = compared.to_artifact()
        except ValueError:
            comparison = None       # unusable reference: diagnose without it
    return diagnosis_output(result, comparison, root)


def _handle_replay(message: ExecutionMessage) -> dict[str, Any]:
    data = message.data or {}
    refs = _trace_refs(data)
    if not refs:
        raise _TaskFailed(
            "no trace to replay: set data.trace_ref to a ref returned by a previous "
            f"'{CAP_BUG_LOCALIZATION}' or '{CAP_DIAGNOSIS}' step."
        )
    view = replay(ReplayInput(trace_path=resolve_trace_ref(refs[0]), **_nav_fields(data)))
    if view.status == "FAILED":
        raise _TaskFailed(view.error or view.message)
    return {
        "summary": view.message,
        "cursor": view.cursor,
        "total": view.total,
        "can_forward": view.can_forward,
        "can_back": view.can_back,
        "current": view.current,
        "timeline": view.timeline,
        "def_of": view.def_of,
        "trace_ref": refs[0] if refs[0].startswith(TRACE_REF_PREFIX) else make_trace_ref(refs[0]),
    }


def _handle_trace_alignment(message: ExecutionMessage) -> dict[str, Any]:
    data = message.data or {}
    refs = _trace_refs(data)
    if len(refs) < 2:
        raise _TaskFailed(
            "alignment compares runs of the same program: set data.trace_refs to at "
            "least two refs (two for a side-by-side comparison, three or more to "
            "curate them as a set)."
        )
    paths = [resolve_trace_ref(r) for r in refs]
    result = compare(AlignInput(trace_paths=paths, **_nav_fields(data)))
    if result.status == "FAILED":
        raise _TaskFailed(result.error or result.message)

    artifact = result.to_artifact()
    output: dict[str, Any] = {"summary": result.message, "mode": result.mode}
    if result.mode == "pair":
        output.update({
            "distance": result.distance,
            "normalized_distance": result.normalized_distance,
            "matched": result.matched,
            "gaps": result.gaps,
            "aligned": result.aligned,
            "delta": result.delta,
            "divergences": result.divergences,
        })
    else:
        output.update({
            "matrix": result.matrix,
            "lengths": result.lengths,
            "reference": result.reference,
            "outlier": result.outlier,
            "mean_distance": result.mean_distance,
            "reference_trace_ref": (
                make_trace_ref(paths[result.reference]) if result.reference is not None else None
            ),
            "outlier_trace_ref": (
                make_trace_ref(paths[result.outlier]) if result.outlier is not None else None
            ),
        })
    output["trace_refs"] = [make_trace_ref(p) for p in paths]
    output.setdefault("criterion", artifact.get("criterion"))
    return output


class _TaskFailed(Exception):
    """The task could not be completed — reported as ``status: "error"``, HTTP 200."""


_HANDLERS = {
    CAP_BUG_LOCALIZATION: _handle_bug_localization,
    CAP_DIAGNOSIS: _handle_diagnosis,
    CAP_REPLAY: _handle_replay,
    CAP_TRACE_ALIGNMENT: _handle_trace_alignment,
}


def handle(message: ExecutionMessage) -> AgentReply:
    """Answer one KIO1 execution message. Never raises — failures become replies.

    Blocking: call it in a worker thread (``asyncio.to_thread``) so the event loop
    stays free, since KIO1 may dispatch several steps to KIO2 concurrently.
    """
    reply = AgentReply(
        workflow_id=message.workflow_id,
        step_id=message.step_id,
        agent_id=message.agent_id or AGENT_ID,
    )

    capability = (message.capability or "").strip()
    if not capability:
        reply.status, reply.error = "error", (
            "no capability in the message; expected one of: " + ", ".join(CAPABILITIES)
        )
        return reply

    if capability in UNSUPPORTED_CAPABILITIES:
        reply.status, reply.error = "error", UNSUPPORTED_CAPABILITIES[capability]
        return reply

    handler = _HANDLERS.get(capability)
    if handler is None:
        reply.status, reply.error = "error", (
            f"unsupported capability {capability!r}; KIO2 answers: " + ", ".join(CAPABILITIES)
        )
        return reply

    try:
        reply.output = handler(message)
    except (_TaskFailed, ValueError) as exc:
        reply.status, reply.error = "error", str(exc)
    except Exception as exc:  # noqa: BLE001 — a crash must not look like a broken service
        reply.status, reply.error = "error", f"{type(exc).__name__}: {exc}"
    return reply
