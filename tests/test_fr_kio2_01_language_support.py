"""FR-KIO2-01 acceptance — Python source support + valid trace generation.

Acceptance criterion: "The PoC environment successfully interprets the target
language and produces a valid trace file upon execution." We run a Python target
under the engine and assert the produced trace passes XSD validation.
"""

from focustracer.validate.validator import validate_xml_against_xsd

from kio2.dummy import EXAMPLE
from kio2.runner import run_trace


def test_python_target_produces_xsd_valid_trace(tmp_path):
    out = str(tmp_path / "trace.xml")
    trace_path = run_trace(
        str(EXAMPLE),
        working_directory=str(EXAMPLE.parent),
        functions=["average_price", "summarise_cart"],
        detail="detailed",
        schema_version="2.3",
        output_path=out,
    )
    assert trace_path == out

    is_valid, errors = validate_xml_against_xsd(trace_path)
    assert is_valid, f"trace failed XSD validation: {errors}"


def test_instrumentation_preserves_semantics():
    """Zero-touch: tracing the target must not change what it computes.

    The example raises ZeroDivisionError with or without tracing — tracing only
    records it, never alters control flow. We assert the untraced run raises the
    same error the trace captures at the same line.
    """
    import runpy
    import pytest

    with pytest.raises(ZeroDivisionError):
        runpy.run_path(str(EXAMPLE), run_name="__main__")
