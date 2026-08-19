"""The standalone HTTP surface — `/health/`, `/tasks`, `/execute`.

The other suites drive ``kio2_handler`` directly, which leaves the FastAPI layer
itself untested: a request-model wiring mistake there makes every POST fail with
422 *before* the handler runs, while every handler test still passes. These
tests exercise the real ASGI app so the deployed contract is covered.
"""

import pytest

from kio2.service import TASK_ALIGN, TASK_LOCALIZE, TASK_REPLAY, make_app

testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture(scope="module")
def client():
    return testclient.TestClient(make_app())


def test_health_reports_the_service(client):
    body = client.get("/health/").json()
    assert body["status"] == "ok"
    assert body["service"] == "kio2"
    assert "otel" in body


def test_tasks_announces_every_capability(client):
    body = client.get("/tasks").json()
    announced = {t["task_type"] for t in body["supported_tasks"]}
    assert announced == {TASK_LOCALIZE, TASK_REPLAY, TASK_ALIGN}


def test_execute_accepts_a_job_request_envelope(client):
    """A bare payload must reach the handler, not bounce off request validation."""
    res = client.post("/execute", json={"session_id": "s1", "payload": {}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["message_type"] == "JOB_RESULT"
    assert body["session_id"] == "s1"
    assert body["payload"]["status"] in ("DONE", "REVIEW_REQUIRED")
    assert body["payload"]["artifact_data"]["suspect_lines"]


def test_execute_without_a_session_id(client):
    res = client.post("/execute", json={"payload": {}})
    assert res.status_code == 200, res.text


def test_execute_routes_replay_and_alignment_over_http(client):
    """One round trip per task type, chained the way a UI would use them."""
    localized = client.post("/execute", json={"payload": {}}).json()["payload"]
    trace = localized["artifact_data"]["trace_path"]

    replayed = client.post("/execute", json={"payload": {
        "task_type": TASK_REPLAY, "trace_path": trace, "at_exception": True,
    }}).json()["payload"]
    assert replayed["status"] == "DONE"
    assert replayed["artifact_data"]["task_type"] == TASK_REPLAY
    assert replayed["artifact_data"]["current"]["state"]

    aligned = client.post("/execute", json={"payload": {
        "task_type": TASK_ALIGN, "trace_paths": [trace, trace],
    }}).json()["payload"]
    assert aligned["status"] == "DONE"
    assert aligned["artifact_data"]["mode"] == "pair"
    assert aligned["artifact_data"]["distance"] == 0     # a trace against itself


def test_execute_reports_an_unknown_task(client):
    body = client.post("/execute", json={"payload": {"task_type": "teleport"}}).json()
    assert body["payload"]["status"] == "FAILED"
    assert body["payload"]["error"]["error_code"] == "KIO2_UNKNOWN_TASK"
