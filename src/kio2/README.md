# KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing

The AI4SWENG **KIO2** service, built on FocusTracer. It locates the fault behind
a failing execution — records a trace, computes a backward dynamic slice, and
returns **ranked suspect statements** with runtime evidence.

> **Dependency.** FocusTracer stays an independent tool, consumed here as a
> library and not copied into this package. `pip install` of KIO2 installs it
> from its public GitHub repository (see `pyproject.toml`). KIO2 needs version
> 1.9 or later: it imports `core.slicer`, `core.reverse`, `core.explain`, the
> replay engine and `align.TraceSet` / `AlignedPair.seek`.

Per D2.6, KIO2's scope is *localization*. It does **not** generate the fix — that
is **KIO7**. KIO2 packages the slice (`handoff_context`) for KIO7 to consume.

## Design: modular & portable

The package is transport-agnostic and has no hard dependency on the AI4SWENG
platform. The same code runs three ways:

| Mode | How |
|---|---|
| Library call | `from kio2 import localize; localize(inp)` |
| Standalone service | `python -m kio2.main` → FastAPI on :8102 (`/jobs`, `/execute`, `/docs`) |
| Platform KIO shell | drop into `apps/kio_shells/` → `make_app` uses `make_kio_app` |

Layers (each importable on its own):

- `contract.py` — the input/output models for every task (the interface)
- `runner.py` — runs the target under FocusTracer to produce a trace (FR-KIO2-07)
- `localizer.py` — trace → slice → ranked suspects (FR-KIO2-07, FR-KIO2-05 in part)
- `replayer.py` — post-mortem navigation over a recorded trace (FR-KIO2-02)
- `comparator.py` — align traces / curate a trace set (FR-KIO2-03)
- `observability.py` — optional OpenTelemetry spans/metrics (no-op if OTel absent)
- `service.py` — HTTP routes + `make_app` (platform shell or standalone FastAPI)
- `kio1_protocol.py` — adapter for KIO1 messages: capabilities, trace references
- `jobs.py` — the job contract KIO1 dispatches with (`POST /jobs`, `GET /jobs/{id}`)
- `playground.py` + `playground/index.html` — the browser playground at `/playground` (pasted code only with `KIO2_PLAYGROUND_SNIPPETS=1`)
- `openapi_examples.py` — the ready-to-run examples shown at `/docs`
- `dummy.py` + `examples/` — a failing program and its corrected version

The three core modules (`localizer`, `replayer`, `comparator`) depend only on
FocusTracer and `contract`, so each is usable as a plain function as well as over
the HTTP API. Only `runner` executes anything; the rest are read-only over a trace.

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
# standalone service, then open http://127.0.0.1:8102/docs
python -m kio2.main

# one-shot library demo
python -c "from kio2 import localize; from kio2.dummy import dummy_input; print(localize(dummy_input()).message)"

# tests
pytest -q                     # from the repo root
```

## Boundary with KIO7 (fix generation)

KIO2 → `suspect_lines` + `handoff_context` → **KIO7** generates the patch → HITL
approves. In the platform pipeline this mirrors D2.6 UC-UC1-03:
KIO11 (confirm failure) → **KIO2 (localize)** → KIO7 (fix).
