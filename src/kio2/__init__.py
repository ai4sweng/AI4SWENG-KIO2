"""KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing (AI4SWENG).

A modular, transport-agnostic KIO2 service built on FocusTracer. Locates the
fault behind a failing execution (dynamic slicing over a recorded trace) and
hands the evidence to KIO7 for fix generation — it does not generate the fix
itself (D2.6 scope boundary).

Layers (import the one you need):
- ``contract``      — the input/output models for every task (interface)
- ``runner``        — run a target under FocusTracer to get a trace
- ``localizer``     — trace → slice → ranked suspect lines (FR-KIO2-05)
- ``replayer``      — post-mortem navigation over a recorded trace (FR-KIO2-02)
- ``comparator``    — align traces / curate a trace set (FR-KIO2-03)
- ``observability`` — optional OpenTelemetry spans/metrics (no-op if OTel absent)
- ``service``       — KIO handler + app factory (platform make_kio_app or standalone)
- ``dummy``         — a failing-example fixture for standalone runs

``localizer``, ``replayer`` and ``comparator`` depend only on FocusTracer and
``contract``, so each runs as a plain library call as well as over ``/execute``.
"""

from .comparator import compare
from .contract import (
    AlignInput,
    FaultLocalization,
    Kio2Input,
    ReplayInput,
    ReplayView,
    SuspectLine,
    TraceComparison,
)
from .localizer import localize
from .replayer import replay

__all__ = [
    "AlignInput",
    "FaultLocalization",
    "Kio2Input",
    "ReplayInput",
    "ReplayView",
    "SuspectLine",
    "TraceComparison",
    "compare",
    "localize",
    "replay",
]
__version__ = "0.2.0"
