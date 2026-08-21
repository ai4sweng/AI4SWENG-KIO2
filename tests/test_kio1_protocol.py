"""The KIO1 dispatch protocol, as KIO1 actually speaks it.

Request and reply shapes come from the orchestrator's own contract page
(`kio1.orchestrator/docs/connecting-a-kio.md`) and its reference stub
(`tools/dummy_agent.py`). The rules that matter and are pinned here:

* answer HTTP 200 even when the task failed — a non-2xx means *the service is
  broken*, which is a different thing;
* set ``status`` explicitly — KIO1 reads a missing one as ``"ok"``, so a silently
  empty reply would be recorded as a success;
* echo ``workflow_id`` / ``step_id`` — they are how KIO1 matches the step.

The regression that motivated the adapter: KIO2's own envelope answered a KIO1
message with HTTP 200 and none of these fields, so KIO1 logged the step as
successful with no output.
"""

import pytest

from kio2 import kio1
from kio2.service import make_app

testclient = pytest.importorskip("fastapi.testclient")

PRICING = '''
def net_price(item):
    return item["price"] * item["qty"]


def discounted(net, tier):
    rate = {"gold": 0.20, "silver": 0.10}[tier]
    return net * (1 - rate)
'''

ORDERS = '''
from shop.pricing import discounted, net_price


def order_total(items, tier):
    net = 0
    for it in items:
        net += net_price(it)
    return discounted(net, tier)
'''

MAIN = '''
import os

from shop.orders import order_total

CART = [{"price": 100, "qty": 2}, {"price": 30, "qty": 1}]

if __name__ == "__main__":
    print(order_total(CART, os.environ.get("TIER", "bronze")))
'''


@pytest.fixture(scope="module")
def client():
    return testclient.TestClient(make_app())


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """A package-shaped program that raises KeyError on an unknown tier."""
    root = tmp_path_factory.mktemp("kio1repo")
    pkg = root / "shop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "pricing.py").write_text(PRICING, encoding="utf-8")
    (pkg / "orders.py").write_text(ORDERS, encoding="utf-8")
    (root / "main.py").write_text(MAIN, encoding="utf-8")
    return root


def message(capability, repo=None, **data):
    """A KIO1 execution message, shaped exactly like the protocol document's."""
    payload = dict(data)
    if repo is not None:
        payload.setdefault("repository", {"path": str(repo)})
        payload.setdefault("target", {"entry_point": "main.py", "functions": []})
    return {
        "workflow_id": "wf-bug-pay01",
        "step_id": "s2",
        "agent_id": "KIO2",
        "capability": capability,
        "endpoint": "http://127.0.0.1:8102",
        "task": "Locate the fault behind the failing test",
        "data": payload,
    }


# ── envelope rules ──────────────────────────────────────────────────────────


def test_reply_echoes_the_step_identifiers(client, repo):
    body = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()
    assert body["workflow_id"] == "wf-bug-pay01"
    assert body["step_id"] == "s2"
    assert body["agent_id"] == "KIO2"
    assert set(body) == {"workflow_id", "step_id", "agent_id", "status", "output", "error"}


def test_status_is_always_explicit(client, repo):
    """KIO1 treats a missing status as success, so it must never be omitted."""
    for msg in (message(kio1.CAP_BUG_LOCALIZATION, repo), message("nonsense")):
        body = client.post("/execute", json=msg).json()
        assert body["status"] in ("ok", "error")


def test_a_failed_task_is_still_http_200(client):
    """`status: error` inside a 200 — not a 4xx/5xx, which means "service broken"."""
    response = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "entry point" in body["error"]
    assert body["output"] is None


def test_a_message_without_a_capability_is_an_error_not_a_dummy_run(client):
    """The original silent-failure trap: it must not fall through to the other envelope."""
    body = client.post("/execute", json={"workflow_id": "wf-1", "step_id": "s1"}).json()
    assert body["status"] == "error"
    assert "capability" in body["error"]


def test_unknown_capability_lists_what_kio2_answers(client):
    body = client.post("/execute", json=message("time_travel")).json()
    assert body["status"] == "error"
    assert kio1.CAP_BUG_LOCALIZATION in body["error"]


# ── bug_localization ────────────────────────────────────────────────────────


def test_bug_localization_returns_summary_and_findings(client, repo):
    """The shape KIO1's own reference stub returns, so its prompt/UI fit."""
    out = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()["output"]
    assert out["summary"]
    assert out["findings"]
    top = out["findings"][0]
    assert top["file"] == "shop/pricing.py"      # repo-relative, POSIX separators
    assert top["function"] == "discounted"
    assert top["dependency"] == "criterion"
    assert 0.0 < top["confidence"] <= 1.0
    assert "[tier]" in top["description"]


def test_bug_localization_carries_the_recorded_values(client, repo):
    out = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()["output"]
    assert out["crash_state"]["tier"] == "'bronze'"
    assert out["criterion"].startswith("exception@")
    assert out["hitl_required"] is False


def test_findings_never_leak_container_paths(client, repo):
    """Absolute paths from inside KIO2's container are meaningless to KIO1."""
    out = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()["output"]
    assert str(repo) not in out["summary"]
    assert all(not f["file"].startswith(str(repo)) for f in out["findings"])


# ── diagnosis ───────────────────────────────────────────────────────────────


def test_diagnosis_states_the_causal_chain(client, repo):
    out = client.post("/execute", json=message(kio1.CAP_DIAGNOSIS, repo)).json()["output"]
    assert "discounted" in out["root_cause"]
    assert "tier='bronze'" in out["root_cause"].replace("tier = 'bronze'", "tier='bronze'")
    assert out["compared_runs"] == 1
    assert out["slice_context"]                 # what KIO7 needs
    assert any(e["kind"] == "recorded_value" for e in out["evidence"])


def test_diagnosis_with_a_reference_run_reports_the_difference(client, repo):
    """A passing run turns "where it broke" into "how this run differed"."""
    import os

    from kio2.runner import run_trace
    os.environ["TIER"] = "gold"
    try:
        passing = run_trace("main.py", working_directory=str(repo))
    finally:
        os.environ.pop("TIER", None)

    msg = message(kio1.CAP_DIAGNOSIS, repo, reference={"trace_ref": kio1.make_trace_ref(passing)})
    out = client.post("/execute", json=msg).json()["output"]
    assert out["compared_runs"] == 2
    assert any(e["kind"] in ("divergence", "value_difference") for e in out["evidence"])


# ── replay and alignment, driven by trace_ref ───────────────────────────────


def test_replay_follows_a_trace_ref_from_an_earlier_step(client, repo):
    """The hand-off KIO1 makes: one step's output becomes the next step's data."""
    first = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()
    ref = first["output"]["trace_ref"]
    assert ref.startswith(kio1.TRACE_REF_PREFIX)

    body = client.post("/execute", json=message(
        kio1.CAP_REPLAY, trace_ref=ref, at_exception=True, step_action="out",
    )).json()
    assert body["status"] == "ok"
    assert body["output"]["current"]["state"]
    assert body["output"]["total"] > 0


def test_replay_accepts_a_ref_inherited_from_upstream(client, repo):
    first = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()
    msg = message(kio1.CAP_REPLAY, upstream={"s2": first["output"]})
    body = client.post("/execute", json=msg).json()
    assert body["status"] == "ok", body["error"]
    assert body["output"]["cursor"] == 0


def test_replay_without_a_trace_says_what_to_send(client):
    body = client.post("/execute", json=message(kio1.CAP_REPLAY)).json()
    assert body["status"] == "error"
    assert "trace_ref" in body["error"]


def test_trace_alignment_compares_two_runs(client, repo):
    first = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()
    ref = first["output"]["trace_ref"]
    body = client.post("/execute", json=message(
        kio1.CAP_TRACE_ALIGNMENT, trace_refs=[ref, ref],
    )).json()
    assert body["status"] == "ok", body["error"]
    assert body["output"]["mode"] == "pair"
    assert body["output"]["distance"] == 0       # a trace against itself


def test_trace_alignment_needs_two_traces(client, repo):
    first = client.post("/execute", json=message(kio1.CAP_BUG_LOCALIZATION, repo)).json()
    body = client.post("/execute", json=message(
        kio1.CAP_TRACE_ALIGNMENT, trace_refs=[first["output"]["trace_ref"]],
    )).json()
    assert body["status"] == "error"
    assert "at least two" in body["error"]


# ── fix_recommendation: declared by KIO1, out of KIO2's scope ───────────────


def test_fix_recommendation_is_refused_with_an_actionable_reason(client, repo):
    """KIO1's config asks KIO2 for this; D2.6 UC-UC1-03 makes it KIO7's step."""
    body = client.post("/execute", json=message(kio1.CAP_FIX_RECOMMENDATION, repo)).json()
    assert body["status"] == "error"
    assert "KIO7" in body["error"]
    assert kio1.CAP_DIAGNOSIS in body["error"]


def test_declared_capabilities_exclude_the_unsupported_one(client):
    body = client.get("/tasks").json()
    assert body["agent_id"] == "KIO2"
    assert kio1.CAP_FIX_RECOMMENDATION not in body["capabilities"]
    assert kio1.CAP_FIX_RECOMMENDATION in body["unsupported_capabilities"]
    assert set(body["capabilities"]) == set(kio1.CAPABILITIES)


# ── trace references ────────────────────────────────────────────────────────


def test_trace_ref_round_trips(tmp_path):
    trace = tmp_path / "t.xml"
    trace.write_text("<trace/>", encoding="utf-8")
    assert kio1.resolve_trace_ref(kio1.make_trace_ref(str(trace))) == str(trace.resolve())


def test_trace_ref_outside_the_trace_directory_is_refused():
    """The adapter is the network edge: no reading arbitrary files off disk."""
    with pytest.raises(ValueError, match="outside the trace directory"):
        kio1.resolve_trace_ref(kio1.make_trace_ref("/etc/passwd"))


def test_malformed_trace_ref_is_rejected():
    with pytest.raises(ValueError):
        kio1.resolve_trace_ref(kio1.TRACE_REF_PREFIX + "!!!not-base64!!!")


def test_a_refused_ref_becomes_a_task_error_not_a_crash(client):
    body = client.post("/execute", json=message(
        kio1.CAP_REPLAY, trace_ref=kio1.make_trace_ref("/etc/passwd"),
    )).json()
    assert body["status"] == "error"
    assert body["output"] is None


# ── the recording budget ────────────────────────────────────────────────────


def test_localization_stays_inside_kio1s_dispatch_window():
    """KIO1 waits 60 s and does not retry, so recording must finish sooner."""
    assert kio1.TRACE_BUDGET_SECONDS < 60
    inp = kio1.localization_input(kio1.ExecutionMessage(
        capability=kio1.CAP_BUG_LOCALIZATION,
        data={"target": {"entry_point": "main.py"}, "repository": {"path": "/work"}},
    ))
    assert inp.trace_timeout == kio1.TRACE_BUDGET_SECONDS


# ── the other envelope still works ──────────────────────────────────────────


def test_kio2s_own_contract_is_unaffected(client):
    """Same path, other shape — the pre-existing contract must not regress."""
    body = client.post("/execute", json={"session_id": "s1", "payload": {}}).json()
    assert body["message_type"] == "JOB_RESULT"
    assert body["source"] == "kio2"
    assert body["payload"]["artifact_data"]["suspect_lines"]


def test_health_answers_both_spellings(client):
    """KIO2's docs use /health/, KIO1 probes /health."""
    for path in ("/health", "/health/"):
        body = client.get(path).json()
        assert body["status"] == "ok"
        assert body["agent_id"] == "KIO2"
