"""Optional OpenTelemetry instrumentation for KIO2.

Designed for the AI4SWENG program-wide observability stack: each KIO emits
spans and metrics to the *global* OpenTelemetry providers, and the host
environment (the OTEL collector / Grafana setup being developed in parallel)
wires the actual OTLP exporter via standard env vars. This module therefore
never configures an exporter itself — it only emits.

If ``opentelemetry`` is not installed, every call here is a no-op, so the
core service runs unchanged with or without the observability stack.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:  # OTel is optional
    from opentelemetry import metrics, trace

    _tracer = trace.get_tracer("kio2")
    _meter = metrics.get_meter("kio2")
    _dur = _meter.create_histogram(
        "kio2.localization.duration", unit="ms",
        description="Wall time of a KIO2 fault-localization run",
    )
    _suspects = _meter.create_histogram(
        "kio2.localization.suspect_count", unit="1",
        description="Number of suspect statements returned",
    )
    _conf = _meter.create_histogram(
        "kio2.localization.confidence", unit="1",
        description="Localization confidence (0..1)",
    )
    _runs = _meter.create_counter(
        "kio2.localization.runs", unit="1",
        description="Count of localization runs by status",
    )
    _OTEL = True
except Exception:  # pragma: no cover - depends on host env
    _OTEL = False


@contextmanager
def localization_span(session_id: str, target: str = "") -> Iterator[dict]:
    """Wrap a localization run in a span; yields a dict to stash timing.

    Usage::

        with localization_span(sid, target) as ctx:
            result = localize(inp)
            ctx["result"] = result
        # metrics are recorded on exit
    """
    ctx: dict = {"_t0": time.perf_counter()}
    if not _OTEL:
        try:
            yield ctx
        finally:
            _record_from_ctx(ctx)
        return

    with _tracer.start_as_current_span("kio2.localize") as span:
        span.set_attribute("kio2.session_id", session_id)
        if target:
            span.set_attribute("kio2.target", target)
        try:
            yield ctx
        finally:
            result = ctx.get("result")
            if result is not None:
                span.set_attribute("kio2.status", getattr(result, "status", "UNKNOWN"))
                span.set_attribute("kio2.confidence", float(getattr(result, "confidence", 0.0)))
                span.set_attribute("kio2.suspect_count", int(getattr(result, "slice_size", 0)))
            _record_from_ctx(ctx)


def _record_from_ctx(ctx: dict) -> None:
    if not _OTEL:
        return
    duration_ms = (time.perf_counter() - ctx.get("_t0", time.perf_counter())) * 1000.0
    result = ctx.get("result")
    status = getattr(result, "status", "UNKNOWN") if result is not None else "ERROR"
    attrs = {"status": status}
    try:
        _dur.record(duration_ms, attrs)
        _runs.add(1, attrs)
        if result is not None:
            _suspects.record(int(getattr(result, "slice_size", 0)), attrs)
            _conf.record(float(getattr(result, "confidence", 0.0)), attrs)
    except Exception:  # pragma: no cover
        pass


def otel_enabled() -> bool:
    """True if OpenTelemetry is importable (metrics/spans will be emitted)."""
    return _OTEL
