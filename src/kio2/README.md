# KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing

The AI4SWENG **KIO2** service, built on FocusTracer. It locates the fault behind
a failing execution — records a trace, computes a backward dynamic slice, and
returns **ranked suspect statements** with runtime evidence.

> **Home & dependency.** This is the KIO2 *service*; it lives in the AI4SWENG
> platform (or the standalone KIO2 repo). **FocusTracer stays an independent
> tool** and is consumed here as a library dependency — it is *not* vendored
> inside this package. Install it separately (see `requirements.txt`):
> `pip install -e path/to/focustracer` — **version >= 1.8**, since KIO2 imports
> `core.slicer`, `core.reverse`, `core.explain` and the replay/align engine.
> KIO2 = the consumer; FocusTracer = the engine.

Per D2.6, KIO2's scope is *localization*. It does **not** generate the fix — that
is **KIO7**. KIO2 packages the slice (`handoff_context`) for KIO7 to consume.

## Design: modular & portable

The package is transport-agnostic and has no hard dependency on the AI4SWENG
platform. The same code runs three ways:

| Mode | How |
|---|---|
| Library call | `from kio2 import localize; localize(inp)` |
| Standalone service | `python -m kio2.main` → FastAPI `/execute` |
| Platform KIO shell | drop into `apps/kio_shells/` → `make_app` uses `make_kio_app` |

Layers (each importable on its own):

- `contract.py` — `Kio2Input` / `FaultLocalization` / `SuspectLine` (the interface)
- `runner.py` — runs the target under FocusTracer to produce a trace
- `localizer.py` — trace → slice → ranked suspects (**core; depends only on FocusTracer**)
- `observability.py` — optional OpenTelemetry spans/metrics (no-op if OTel absent)
- `service.py` — KIO handler + `make_app` (platform shell or standalone FastAPI)
- `dummy.py` + `examples/` — a bundled failing example for standalone runs

## Contract

**Input** (`Kio2Input` / envelope payload):

```json
{
  "target_script": "path/to/failing_entrypoint.py",
  "working_directory": "repo/root",
  "functions": ["average_price", "summarise_cart"],
  "criterion": null,
  "failing_test": "test_x — ZeroDivisionError (from KIO11, dummy for now)"
}
```

`criterion` is `null` to localize at the crash, or `[FILE:]LINE[:VAR]` to target a
specific value. When upstream KIOs aren't wired yet, a bare payload falls back to
the bundled dummy example.

**Output** (`FaultLocalization` / artifact_data):

```json
{
  "status": "DONE",
  "criterion": "exception@buggy_order_total.py:15",
  "suspect_lines": [
    {"rank": 1, "score": 1.0, "dependency": "criterion",
     "function": "average_price", "line": 15, "source": "return total / len(prices)"}
  ],
  "crash_state": {"prices": {"value": "[]", "type": "list"}},
  "confidence": 0.85,
  "handoff_context": "<value-annotated slice for KIO7>"
}
```

`status` is `REVIEW_REQUIRED` when confidence is low (HITL gate); the handler adds
a `hitl_question`. `status` is `FAILED` with an `error` when the target can't be
traced.

## Observability

`observability.py` emits spans (`kio2.localize`) and metrics
(`kio2.localization.{duration,suspect_count,confidence,runs}`) to the **global**
OpenTelemetry providers. It never configures an exporter — the host environment
(the program-wide OTEL collector → Grafana) wires OTLP via standard env vars. With
no OpenTelemetry installed, all calls are no-ops.

## Run & test

```bash
# standalone service (needs focustracer installed / on PYTHONPATH)
python -m kio2.main            # serves on :8013

# one-shot library demo
python -c "from kio2 import localize; from kio2.dummy import dummy_input; print(localize(dummy_input()).message)"

# tests
pytest -q                     # from the repo root
```

## Boundary with KIO7 (fix generation)

KIO2 → `suspect_lines` + `handoff_context` → **KIO7** generates the patch → HITL
approves. In the platform pipeline this mirrors D2.6 UC-UC1-03:
KIO11 (confirm failure) → **KIO2 (localize)** → KIO7 (fix).
