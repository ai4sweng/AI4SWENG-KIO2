"""Ready-to-run request bodies for the interactive API docs (``/docs``).

Each example names a program bundled with KIO2, at its path on the machine the
service runs on, so "Try it out" then "Execute" works without editing anything.
The examples that need a recording (replay, alignment) carry a placeholder to
replace with the ``trace_ref`` of an earlier result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
FAILING = "buggy_order_total.py"
PASSING = "fixed_order_total.py"
TRACE_PLACEHOLDER = "kio2://trace/PASTE-THE-trace_ref-OF-AN-EARLIER-RESULT"

API_DESCRIPTION = """
KIO2 runs a Python program once, records every executed line, and works back
from the error to the lines that caused it.

**Try it in three clicks**

1. Open **POST /jobs**, press *Try it out*, pick the example
   *bug_localization: failing example* and press *Execute*. Copy the `job_id`.
2. Open **GET /jobs/{job_id}**, paste the `job_id` and execute until `status`
   is `success`. The `output` holds the findings and a `trace_url`.
3. Open the `trace_url` (on this server) to see the recorded trace as XML.

**POST /execute** does the same in one synchronous call.

A job is identified by `workflow_id` + `step_id`: sending the same pair again
returns the existing job. Change `step_id` to run it again.
"""


def _ref(path: Path) -> dict[str, str]:
    return {"uri": path.as_uri()}


def _job(step_id: str, capability: str, data: dict[str, Any], task: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "workflow_id": "wf-docs",
        "step_id": step_id,
        "capability": capability,
        "task": task,
        "data": data,
    }


def _code(script: str) -> dict[str, Any]:
    return {"repository": _ref(EXAMPLES_DIR), "entry_point": _ref(EXAMPLES_DIR / script)}


def job_examples() -> dict[str, dict[str, Any]]:
    """Examples for ``POST /jobs``, the contract KIO1 dispatches with."""
    return {
        "bug_localization": {
            "summary": "bug_localization: failing example",
            "description": "A cart with no item in stock divides by zero. Expect verdict `defect` at line 15.",
            "value": _job("s-localize", "bug_localization", _code(FAILING), "Find the fault"),
        },
        "clean": {
            "summary": "bug_localization: corrected example",
            "description": "The same program with a guard. Expect `success` with verdict `clean`.",
            "value": _job("s-clean", "bug_localization", _code(PASSING), "Check the corrected program"),
        },
        "diagnosis": {
            "summary": "diagnosis: root cause and evidence",
            "description": "Expect `root_cause` and `slice_context` in the output.",
            "value": _job("s-diagnosis", "diagnosis", _code(FAILING), "Explain the failure"),
        },
        "replay": {
            "summary": "replay: open a recording at the failure",
            "description": "Replace the placeholder with the `trace_ref` from an earlier result.",
            "value": _job("s-replay", "replay", {"trace": {"uri": TRACE_PLACEHOLDER}}, "Open the recording"),
        },
        "alignment": {
            "summary": "trace_alignment: compare two recordings",
            "description": "Replace both placeholders with `trace_ref` values, e.g. of the failing and the corrected run.",
            "value": _job("s-align", "trace_alignment", {
                "failing": {"uri": TRACE_PLACEHOLDER},
                "passing": {"uri": TRACE_PLACEHOLDER + "-2"},
            }, "Compare the runs"),
        },
        "missing_entry_point": {
            "summary": "failure: no entry point",
            "description": "What KIO1's planner sends today. Expect `failure` with `entry_point_missing`.",
            "value": _job("s-no-entry", "bug_localization", {}, "Locate the fault in the payment module"),
        },
    }


def execute_examples() -> dict[str, dict[str, Any]]:
    """Examples for ``POST /execute``, the synchronous call."""
    def message(step_id: str, capability: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"workflow_id": "wf-docs", "step_id": step_id, "capability": capability,
                "task": "Try it from the API docs", "data": data}

    code = {"repository": {"path": str(EXAMPLES_DIR)}, "target": {"entry_point": FAILING}}
    return {
        "bug_localization": {
            "summary": "bug_localization: failing example",
            "description": "Answers in one call with findings, crash_state and trace_url.",
            "value": message("s1", "bug_localization", code),
        },
        "diagnosis": {
            "summary": "diagnosis: root cause and evidence",
            "value": message("s2", "diagnosis", code),
        },
        "replay": {
            "summary": "replay: step back from the failure",
            "description": "Replace the placeholder with a `trace_ref`. `def_var` shows where `prices` got its value.",
            "value": message("s3", "replay", {
                "trace_ref": TRACE_PLACEHOLDER, "at_exception": True, "def_var": "prices", "window": 2,
            }),
        },
    }
