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


def test_a_relative_working_directory_is_resolved(tmp_path, monkeypatch):
    """The engine runs inside the project root, so relative paths must be made
    absolute first; otherwise the run records nothing and looks clean."""
    from kio2.contract import Kio2Input
    from kio2.localizer import localize

    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "boom.py").write_text(
        "def boom(xs):\n    return xs[len(xs)]\n\nboom([1, 2])\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = localize(Kio2Input(target_script="boom.py", working_directory="proj"))
    assert result.suspect_lines and result.suspect_lines[0].line == 2


def test_a_run_that_records_nothing_is_not_reported_clean(tmp_path):
    """A crash outside every traced function leaves an empty trace: no evidence."""
    from kio2.contract import Kio2Input
    from kio2.localizer import localize

    (tmp_path / "mod.py").write_text(
        "def unused():\n    return 1\n\nraise RuntimeError('at module level')\n", encoding="utf-8")
    result = localize(Kio2Input(target_script="mod.py", working_directory=str(tmp_path)))
    assert result.status == "FAILED"
    assert "No traced statement executed" in result.message


def test_a_failure_missing_from_the_trace_is_not_reported_clean(tmp_path):
    """Deep recursion can stop the recording before the error is written. The
    engine still exits non-zero, and that must not read as a clean run."""
    from kio2.contract import Kio2Input
    from kio2.localizer import localize

    (tmp_path / "deep.py").write_text(
        "def down(n):\n    return down(n + 1)\n\ndown(0)\n", encoding="utf-8")
    result = localize(Kio2Input(target_script="deep.py", working_directory=str(tmp_path)))
    assert result.status != "DONE" or result.suspect_lines
    assert "No runtime defect" not in result.message
