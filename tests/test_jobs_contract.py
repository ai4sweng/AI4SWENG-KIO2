"""The KIO1 job contract — ``POST /jobs`` + ``GET /jobs/{job_id}``.

This is the contract KIO1's dispatcher (``kio10/transport.py`` in the
orchestrator) applies to every agent, so these tests hold KIO2 to what that
dispatcher checks: the echoed envelope, ``schema_version`` 1.0, a plain
``job_id``, ``accepted`` while running, and a final ``success`` whose artifacts
each carry ``receipt.uri`` — or a ``failure`` with a string ``failure_class``.
"""

import re
import time
from pathlib import Path

import pytest

from kio2 import jobs, kio1_protocol
from kio2.service import make_app

testclient = pytest.importorskip("fastapi.testclient")

EXAMPLES = Path(kio1_protocol.__file__).parent / "examples"
JOB_ID = re.compile(r"^[A-Za-z0-9._:-]+$")          # KIO1's check on job ids


@pytest.fixture(scope="module")
def client():
    # The context manager keeps the app's event loop alive between requests,
    # which the background job needs in order to finish.
    with testclient.TestClient(make_app()) as c:
        yield c


def _ref(uri: str, schema_id: str = "x/1.0") -> dict:
    return {"uri": uri, "schema_id": schema_id}


def _request(step_id: str, capability: str, data: dict, workflow_id: str = "wf-jobs") -> dict:
    return {"schema_version": "1.0", "workflow_id": workflow_id, "step_id": step_id,
            "capability": capability, "task": "test", "data": data}


def _run(client, request: dict, timeout: float = 120) -> dict:
    """Submit and poll the way KIO1's `run_job` does, checking the envelope each time."""
    ack = client.post("/jobs", json=request)
    assert ack.status_code == 200, ack.text
    ack = ack.json()
    assert ack["status"] == "accepted"
    assert JOB_ID.fullmatch(ack["job_id"])
    deadline = time.monotonic() + timeout
    while True:
        reply = client.get(f"/jobs/{ack['job_id']}").json()
        for key in ("workflow_id", "step_id"):
            assert reply[key] == request[key]
        assert reply["schema_version"] == "1.0"
        assert reply["job_id"] == ack["job_id"]
        if reply["status"] != "accepted":
            return reply
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.2)


def _example_refs() -> dict:
    return {
        "repository": _ref(EXAMPLES.as_uri(), "source_repository/1.0"),
        "entry_point": _ref((EXAMPLES / "buggy_order_total.py").as_uri(), "python_script/1.0"),
    }


# ── translation ──────────────────────────────────────────────────────────────


def test_file_uris_become_paths():
    assert jobs.uri_to_path("file:///workspace/repo") == "/workspace/repo"
    assert jobs.uri_to_path("file:///E:/code/my%20repo") == "E:/code/my repo"
    assert jobs.uri_to_path("/already/a/path") == "/already/a/path"


def test_references_become_the_execute_fields():
    message = jobs.execution_message(_request("s1", "bug_localization", _example_refs()))
    assert Path(message.data["repository"]["path"]) == EXAMPLES
    assert message.data["target"]["entry_point"] == "buggy_order_total.py"
    assert message._trace_budget == jobs.JOB_TRACE_BUDGET_SECONDS


def test_every_trace_uri_is_collected_whatever_its_name():
    data = {"trace": _ref("kio2://trace/a"), "s2.trace": _ref("kio2://trace/b"),
            "fault_localization": _ref("kio2://jobs/j/fault_localization")}
    message = jobs.execution_message(_request("s3", "trace_alignment", data))
    assert message.data["trace_refs"] == ["kio2://trace/a", "kio2://trace/b"]


def test_replay_opens_at_the_failure_when_no_cursor_is_given():
    message = jobs.execution_message(_request("s2", "replay", {"trace": _ref("kio2://trace/a")}))
    assert message.data["at_exception"] is True


def test_a_request_body_cannot_raise_the_recording_budget():
    message = kio1_protocol.ExecutionMessage(**{"capability": "bug_localization", "_trace_budget": 9999})
    assert message._trace_budget is None


# ── over HTTP ────────────────────────────────────────────────────────────────


def test_tasks_announces_the_job_contract(client):
    body = client.get("/tasks").json()
    assert body["job_contract"]["schema_version"] == "1.0"
    assert "trace" in body["job_contract"]["artifacts"]


def test_localization_then_replay_through_artifacts(client):
    """The chain KIO1 builds from `depends_on`: s1's artifacts become s2's data."""
    first = _run(client, _request("s1", "bug_localization", _example_refs()))
    assert first["status"] == "success", first
    artifacts = first["artifacts"]
    assert set(artifacts) == {"fault_localization", "trace"}
    for artifact in artifacts.values():
        assert isinstance(artifact["receipt"]["uri"], str)
    assert first["output"]["verdict"] == "defect"
    assert first["output"]["findings"][0]["line"] == 15

    # What KIO1's `_collect_artifacts` passes to the dependent step.
    passed = {name: {"uri": a["receipt"]["uri"], "schema_id": a["schema_id"]}
              for name, a in artifacts.items()}
    second = _run(client, _request("s2", "replay", passed))
    assert second["status"] == "success", second
    assert second["output"]["current"]["line"] == 15          # opened at the failure
    assert "trace" in second["artifacts"]


def test_a_clean_run_is_a_success(client, tmp_path):
    (tmp_path / "ok.py").write_text("def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n")
    reply = _run(client, _request("s-clean", "bug_localization", {
        "repository": _ref(tmp_path.as_uri()), "entry_point": _ref((tmp_path / "ok.py").as_uri()),
    }))
    assert reply["status"] == "success", reply
    assert reply["output"]["verdict"] == "clean"
    assert reply["output"]["findings"] == []


@pytest.mark.parametrize("capability, data, expected", [
    ("bug_localization", {}, "entry_point_missing"),
    ("fix_recommendation", {}, "unsupported_capability"),
    ("replay", {}, "trace_unavailable"),
])
def test_failures_are_classified(client, capability, data, expected):
    reply = _run(client, _request(f"s-{expected}", capability, data))
    assert reply["status"] == "failure"
    assert reply["failure_class"] == expected
    assert reply["diagnostics"]["message"]


def test_resubmission_returns_the_same_job(client):
    request = _request("s-repeat", "fix_recommendation", {})
    first = client.post("/jobs", json=request).json()["job_id"]
    again = client.post("/jobs", json=request).json()["job_id"]
    assert first == again


def test_malformed_requests_and_unknown_jobs(client):
    bad_version = _request("s1", "replay", {})
    bad_version["schema_version"] = "2.0"
    assert client.post("/jobs", json=bad_version).status_code == 422
    assert client.post("/jobs", json={"capability": "replay"}).status_code == 422
    assert client.get("/jobs/no-such-job").status_code == 404


# ── trace access ─────────────────────────────────────────────────────────────


def test_trace_dir_follows_the_environment(monkeypatch, tmp_path):
    from kio2.runner import trace_dir
    target = tmp_path / "traces"
    monkeypatch.setenv("KIO2_TRACE_DIR", str(target))
    assert trace_dir() == target.resolve()
    assert target.is_dir()                       # created on first use


def test_a_recording_opens_at_its_trace_url(client):
    reply = _run(client, _request("s-url", "bug_localization", _example_refs()))
    url = reply["output"]["trace_url"]
    assert url.startswith("/traces/")
    res = client.get(url)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert b"<trace" in res.content and b"ZeroDivisionError" in res.content


def test_trace_urls_outside_the_trace_directory_are_refused(client):
    import base64
    token = base64.urlsafe_b64encode(str(Path(__file__).resolve()).encode()).decode().rstrip("=")
    assert client.get(f"/traces/{token}").status_code == 404
