"""KIO2 service tests — end-to-end fault localization over the dummy example."""

import asyncio

from kio2 import localize
from kio2.contract import Kio2Input
from kio2.dummy import EXAMPLE, dummy_input
from kio2.service import kio2_handler


def test_localize_dummy_finds_fault_line():
    """The bundled ZeroDivisionError example localises to the division line."""
    result = localize(dummy_input())
    assert result.status == "DONE"
    assert result.confidence >= 0.6
    # #1 suspect is the criterion (the crash statement) — the division.
    top = result.suspect_lines[0]
    assert top.rank == 1
    assert top.dependency == "criterion"
    assert top.line == 15
    assert "len(prices)" in top.source
    # crash state was reconstructed and the empty list is visible.
    assert "prices" in result.crash_state
    # KIO2 stops at localization: it packages context for KIO7, no patch.
    assert result.handoff_context


def test_suspects_ranked_by_evidence():
    result = localize(dummy_input())
    scores = [s.score for s in result.suspect_lines]
    assert scores == sorted(scores, reverse=True)  # ranked high→low
    assert result.suspect_lines[0].score == 1.0    # criterion weighted highest


def test_missing_target_uses_dummy_and_succeeds():
    """A bare payload (no target_script) falls back to the dummy example."""
    async def _run():
        env = type("E", (), {"payload": {}, "session_id": "s1"})()
        return await kio2_handler(env)

    out = asyncio.run(_run())
    assert out["status"] in ("DONE", "REVIEW_REQUIRED")
    assert out["artifact_data"]["kio"] == "kio2"
    assert out["artifact_data"]["suspect_lines"]


def test_handler_maps_to_kio_contract():
    async def _run():
        payload = dummy_input().to_payload()
        env = type("E", (), {"payload": payload, "session_id": "s2"})()
        return await kio2_handler(env)

    out = asyncio.run(_run())
    assert out["status"] == "DONE"
    assert "artifact_id" in out
    assert out["artifact_data"]["criterion"].startswith("exception@")
    assert out["artifact_data"]["confidence"] >= 0.6


def test_failed_trace_returns_failed_status():
    """A non-existent target yields a FAILED localization, not a crash."""
    result = localize(Kio2Input(target_script="/no/such/file_xyz.py"))
    assert result.status == "FAILED"
    assert result.error


def test_example_file_exists():
    assert EXAMPLE.exists()
