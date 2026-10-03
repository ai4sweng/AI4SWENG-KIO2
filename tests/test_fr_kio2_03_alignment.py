"""FR-KIO2-03 acceptance — trace alignment over the KIO2 contract.

Invariant: *"The distance between identical traces is 0."*
Output: *"A measure of the difference between two execution traces …"* and
*"an encoding of how traces can be aligned with each other."*
Objective: *"manipulation of multiple execution traces within a single
interactive session"* and *"lays down foundation to curate sets of execution
traces"* over the Input, *"a set of execution traces relating to a single
program ran with the different inputs and configurations"*.
"""

import asyncio

from kio2 import compare
from kio2.contract import AlignInput
from kio2.service import _SUPPORTED_TASKS, TASK_ALIGN, kio2_handler


def _cmp(paths, **kw):
    return compare(AlignInput(trace_paths=paths, **kw))


# ── the invariant and the distance measure ──────────────────────────────────


def test_identical_runs_have_distance_zero(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["two_b"]])
    assert res.status == "DONE"
    assert res.mode == "pair"
    assert res.distance == 0                    # the FR-KIO2-03 invariant
    assert res.normalized_distance == 0.0
    assert res.gaps == 0


def test_a_trace_against_itself_has_distance_zero(trace_set):
    assert _cmp([trace_set["five"], trace_set["five"]]).distance == 0


def test_divergent_runs_have_positive_distance(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["five"]])
    assert res.distance > 0
    assert 0.0 < res.normalized_distance <= 1.0
    assert res.gaps > 0


def test_distance_is_symmetric(trace_set):
    ab = _cmp([trace_set["two_a"], trace_set["five"]]).distance
    ba = _cmp([trace_set["five"], trace_set["two_a"]]).distance
    assert ab == ba


# ── the alignment encoding ──────────────────────────────────────────────────


def test_divergences_account_for_every_gap(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["five"]])
    assert res.divergences
    assert sum(d["length"] for d in res.divergences) == res.gaps
    assert all(d["side"] in ("a", "b") for d in res.divergences)


def test_raw_pairs_are_opt_in(trace_set):
    """The pair list is large; it ships only when the caller asks for it."""
    assert _cmp([trace_set["two_a"], trace_set["two_b"]]).pairs is None
    with_pairs = _cmp([trace_set["two_a"], trace_set["two_b"]], include_pairs=True)
    assert with_pairs.pairs
    assert len(with_pairs.pairs) >= with_pairs.matched


# ── multiple traces in a single session ─────────────────────────────────────


def test_cursor_on_a_maps_to_the_aligned_point_in_b(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["two_b"]], seq=3)
    assert res.aligned is True
    assert res.a_seq == 3 and res.b_seq == 3
    assert res.a["current"]["line"] == res.b["current"]["line"]


def test_stepping_moves_both_cursors_together(trace_set):
    at = _cmp([trace_set["two_a"], trace_set["two_b"]], seq=2)
    stepped = _cmp([trace_set["two_a"], trace_set["two_b"]], seq=2, step_action="into")
    assert stepped.a_seq == at.a_seq + 1
    assert stepped.b_seq == at.b_seq + 1


def test_identical_runs_show_no_value_delta(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["two_b"]], seq=3)
    assert res.delta == []


def test_divergent_runs_expose_value_deltas(trace_set):
    """Same statement, different recorded values — what the comparison is for."""
    seen = set()
    for seq in range(0, 8):
        res = _cmp([trace_set["two_a"], trace_set["five"]], seq=seq)
        if res.aligned:
            seen.update(d["name"] for d in res.delta)
    assert seen, "expected at least one variable to differ between the two runs"


# ── trace-set curation ──────────────────────────────────────────────────────


def test_three_traces_are_curated_as_a_set(trace_set):
    res = _cmp([trace_set["two_a"], trace_set["two_b"], trace_set["five"]])
    assert res.status == "DONE"
    assert res.mode == "set"
    assert len(res.matrix) == 3
    assert all(res.matrix[i][i] == 0.0 for i in range(3))                    # d(x, x) = 0
    assert all(res.matrix[i][j] == res.matrix[j][i] for i in range(3) for j in range(3))
    assert res.reference in (0, 1)      # one of the two identical runs
    assert res.outlier == 2             # the divergent one
    assert res.mean_distance > 0
    assert res.lengths and len(res.lengths) == 3


def test_set_reference_is_the_most_representative_run(trace_set):
    res = _cmp([trace_set["five"], trace_set["two_a"], trace_set["two_b"]])
    # The two identical runs are mutually closest, so the reference is one of them.
    assert res.reference in (1, 2)
    assert res.outlier == 0


# ── the API surface ─────────────────────────────────────────────────────────


def test_alignment_is_an_announced_task():
    assert any(t["task_type"] == TASK_ALIGN for t in _SUPPORTED_TASKS)


def test_handler_routes_an_explicit_alignment_task(trace_set):
    async def _go():
        payload = {
            "task_type": TASK_ALIGN,
            "trace_paths": [trace_set["two_a"], trace_set["five"]],
            "seq": 1,
        }
        env = type("E", (), {"payload": payload, "session_id": "s-align"})()
        return await kio2_handler(env)

    out = asyncio.run(_go())
    assert out["status"] == "DONE"
    assert out["artifact_data"]["task_type"] == TASK_ALIGN
    assert out["artifact_data"]["mode"] == "pair"
    assert out["artifact_data"]["distance"] > 0


def test_handler_infers_alignment_from_the_payload_shape(trace_set):
    async def _go():
        payload = {"trace_paths": [trace_set["two_a"], trace_set["two_b"]]}
        env = type("E", (), {"payload": payload, "session_id": "s"})()
        return await kio2_handler(env)

    out = asyncio.run(_go())
    assert out["artifact_data"]["task_type"] == TASK_ALIGN
    assert out["artifact_data"]["distance"] == 0


def test_handler_rejects_an_unknown_task(trace_set):
    async def _go():
        env = type("E", (), {"payload": {"task_type": "teleport"}, "session_id": "s"})()
        return await kio2_handler(env)

    out = asyncio.run(_go())
    assert out["status"] == "FAILED"
    assert out["error"]["error_code"] == "KIO2_UNKNOWN_TASK"


def test_a_single_trace_cannot_be_aligned(trace_set):
    res = _cmp([trace_set["two_a"]])
    assert res.status == "FAILED"
    assert res.error


def test_missing_trace_fails_cleanly(trace_set):
    res = _cmp([trace_set["two_a"], "/no/such/trace_xyz.xml"])
    assert res.status == "FAILED"
    assert res.error
