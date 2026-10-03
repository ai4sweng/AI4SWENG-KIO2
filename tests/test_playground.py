"""The playground routes — the page, its examples, and pasted code.

Pasted code is executed by the next job and the service has no authentication,
so the snippet route must stay closed unless ``KIO2_PLAYGROUND_SNIPPETS`` is set.
"""

import time

import pytest

from kio2 import playground
from kio2.service import make_app

testclient = pytest.importorskip("fastapi.testclient")

FAILING = """
def average(values):
    return sum(values) / len(values)


if __name__ == "__main__":
    average([])
"""


@pytest.fixture()
def client():
    # The context manager keeps the event loop alive between requests, so a
    # submitted job keeps running while the test polls for it.
    with testclient.TestClient(make_app()) as c:
        yield c


@pytest.fixture()
def snippets_on(monkeypatch, tmp_path):
    monkeypatch.setenv("KIO2_PLAYGROUND_SNIPPETS", "1")
    monkeypatch.setattr(playground, "snippet_root", lambda: tmp_path / "snippets")


def _finish(client, request):
    ack = client.post("/jobs", json=request).json()
    for _ in range(200):
        reply = client.get(f"/jobs/{ack['job_id']}").json()
        if reply["status"] != "accepted":
            return reply
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_the_page_is_served(client):
    res = client.get("/playground")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "KIO2 Playground" in res.text


def test_examples_carry_their_source_and_job_references(client):
    body = client.get("/playground/examples").json()
    names = [ex["name"] for ex in body["examples"]]
    assert names == ["buggy_order_total.py", "fixed_order_total.py"]
    for ex in body["examples"]:
        assert "def average_price" in ex["code"]
        assert ex["data"]["entry_point"]["uri"].startswith("file://")
        assert ex["data"]["entry_point"]["uri"].endswith(ex["name"])


def test_snippets_are_refused_by_default(client, monkeypatch):
    monkeypatch.delenv("KIO2_PLAYGROUND_SNIPPETS", raising=False)
    assert client.get("/playground/examples").json()["snippets_enabled"] is False
    res = client.post("/playground/snippets", json={"code": FAILING})
    assert res.status_code == 403
    assert "KIO2_PLAYGROUND_SNIPPETS" in res.json()["detail"]


@pytest.mark.usefixtures("snippets_on")
@pytest.mark.parametrize("body", [
    {"code": ""},
    {"code": FAILING, "filename": "../escape.py"},
    {"code": FAILING, "filename": "notes.txt"},
    {"code": "x" * (playground.MAX_SNIPPET_BYTES + 1)},
])
def test_bad_snippets_are_rejected(client, body):
    assert client.post("/playground/snippets", json=body).status_code == 422


@pytest.mark.usefixtures("snippets_on")
def test_a_pasted_program_runs_through_the_job_contract(client, tmp_path):
    data = client.post("/playground/snippets", json={"code": FAILING, "filename": "avg.py"}).json()
    assert data["entry_point"]["uri"].endswith("/avg.py")
    written = list((tmp_path / "snippets").glob("*/avg.py"))
    assert len(written) == 1 and written[0].read_text(encoding="utf-8") == FAILING

    reply = _finish(client, {
        "schema_version": "1.0", "workflow_id": "wf-playground-test", "step_id": "locate",
        "capability": "bug_localization", "task": "Find the fault", "data": data,
    })
    assert reply["status"] == "success", reply
    assert reply["output"]["verdict"] == "defect"
    assert reply["output"]["findings"][0]["line"] == 3
