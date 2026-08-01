"""KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing (AI4SWENG).

A modular, transport-agnostic KIO2 service built on FocusTracer. Locates the
fault behind a failing execution (dynamic slicing over a recorded trace) and
hands the evidence to KIO7 for fix generation — it does not generate the fix
itself (D2.6 scope boundary).

Layers (import the one you need):
- ``contract``      — Kio2Input / FaultLocalization / SuspectLine (interface)
- ``runner``        — run a target under FocusTracer to get a trace
- ``localizer``     — trace → slice → ranked suspect lines (core, no platform deps)
- ``observability`` — optional OpenTelemetry spans/metrics (no-op if OTel absent)
- ``service``       — KIO handler + app factory (platform make_kio_app or standalone)
- ``dummy``         — a failing-example fixture for standalone runs
"""

from .contract import FaultLocalization, Kio2Input, SuspectLine
from .localizer import localize

__all__ = ["Kio2Input", "FaultLocalization", "SuspectLine", "localize"]
__version__ = "0.1.0"
