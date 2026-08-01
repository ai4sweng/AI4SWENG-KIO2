# KIO2 — Technical Documentation

**KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing**
Owner: BitNet · AI4SWENG · Status: v0.1 (working, dummy-input capable)

---

## 1. What KIO2 does

KIO2 turns a **failing execution** into a **ranked list of suspect statements**
backed by runtime evidence. It records a trace of the failing run, computes a
backward **dynamic slice** from the crash, and scores the statements on that
slice by their causal role. The result tells a developer — or the downstream fix
agent — *where* the bug is, grounded in what actually happened at runtime, not in
an LLM's guess.

**Scope boundary (D2.6).** KIO2 stops at *localization*. It does **not** generate
the fix; that is **KIO7**. KIO2 packages the value-annotated slice as
`handoff_context` for KIO7 to consume. In the program pipeline (D2.6 UC-UC1-03):
**KIO11 confirms the failure → KIO2 localizes → KIO7 fixes → HITL approves.**

The trace/slicing/replay engine underneath is **FocusTracer**, an independent
tool consumed here as a **library dependency** (not vendored). KIO2 is the
AI4SWENG service that wraps FocusTracer behind the KIO contract.

---

## 2. Architecture

```
                    ┌──────────────────────────── KIO2 service ────────────────────────────┐
 failing target ──► │  runner.py ──► FocusTracer ──► trace.xml                               │
 (repo + entry)     │      │            (engine)         │                                   │
                    │      │                             ▼                                   │
                    │      │                        slicer (FocusTracer) ── backward slice   │
                    │      │                             │                                   │
                    │      ▼                             ▼                                   │
                    │  localizer.py ── rank suspects · crash state · handoff_context         │
                    │      │                                                                 │
                    │      ▼                                                                 │
                    │  service.py ── KIO handler (/execute) ──► FaultLocalization artifact   │
                    └──────────────────────────────────────────────────────────────────────┘
                                     │                                        │
                              observability.py                          → hand off to KIO7
                              (OTEL spans+metrics)
```

### Package layers (`src/kio2/`)

| Module | Responsibility | Platform-independent? |
|---|---|---|
| `contract.py` | `Kio2Input`, `FaultLocalization`, `SuspectLine` — the interface | yes |
| `runner.py` | run the target under FocusTracer → produce a trace (subprocess) | yes |
| `localizer.py` | **core**: trace → slice → ranked suspects + crash state + handoff | yes (only depends on FocusTracer) |
| `observability.py` | optional OpenTelemetry spans/metrics (no-op if OTel absent) | yes |
| `service.py` | KIO handler + `make_app` (platform shell **or** standalone FastAPI) | adapter |
| `dummy.py` + `examples/` | bundled failing example for standalone runs | yes |
| `main.py` | service entrypoint (`uvicorn kio2.main:app`) | adapter |

The **core** (`localizer`, `runner`, `contract`, `observability`) has no
dependency on the AI4SWENG platform, so KIO2 runs identically as a library call,
a standalone API, or a platform KIO shell.

---

## 3. Input and Output

### Input — `Kio2Input` (envelope `payload`)

| Field | Type | Meaning |
|---|---|---|
| `target_script` | str (required) | path to the failing script / entrypoint to trace |
| `working_directory` | str | repo root (used as cwd + project root) |
| `functions` | list[str] | trace targets; empty ⇒ trace all functions |
| `criterion` | str \| null | `[FILE:]LINE[:VAR]`; `null` ⇒ localize at the crash |
| `failing_test` | str \| null | failing-test/error context (normally from KIO11; dummy for now) |
| `detail` | str | trace detail level (`detailed` required for slicing) |
| `schema_version` | str | trace schema (slicing needs ≥ `2.3`) |

A bare payload (no `target_script`) falls back to the bundled dummy example.

### Output — `FaultLocalization` (artifact)

```json
{
  "status": "DONE",
  "criterion": "exception@buggy_order_total.py:15",
  "suspect_lines": [
    {"rank": 1, "score": 1.0, "dependency": "criterion",
     "file": "buggy_order_total.py", "function": "average_price",
     "line": 15, "source": "return total / len(prices)"},
    {"rank": 2, "score": 0.5, "dependency": "data",
     "function": "average_price", "line": 11,
     "source": "prices = [it['price'] for it in items if it['in_stock']]"}
  ],
  "crash_state": {"prices": {"value": "[]", "type": "list"}, "total": {"value": "0", "type": "int"}},
  "slice_size": 4,
  "confidence": 0.85,
  "handoff_context": "<value-annotated slice for KIO7>",
  "trace_path": "/tmp/kio2_<id>.xml",
  "message": "Localised to average_price L15: return total / len(prices)  (4 suspect statement(s))"
}
```

- **Scoring**: `criterion` (the crash statement) = 1.0 > `control` = 0.75 > `data` = 0.5, de-duplicated by `file:line`.
- **status**: `DONE` (confidence ≥ 0.6) · `REVIEW_REQUIRED` (low confidence → HITL) · `FAILED` (target could not be traced, with an `error`).

---

## 4. API

The service exposes the KIO contract. Standalone it is a minimal FastAPI app;
inside the platform it is a full KIO shell (see §6).

| Method / Path | Purpose |
|---|---|
| `POST /execute` | JOB_REQUEST → JOB_RESULT (runs localization) |
| `GET /health/` | liveness + `otel` flag |

### Examples

```bash
# health
curl http://localhost:8013/health/

# localize a specific target
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' \
  -d '{"session_id":"s1","payload":{"target_script":"/work/app.py","working_directory":"/work","functions":["compute"]}}'

# bare payload ⇒ bundled dummy example
curl -XPOST http://localhost:8013/execute -H 'content-type: application/json' -d '{"payload":{}}'
```

### Library / one-shot use (no server)

```python
from kio2 import localize
from kio2.contract import Kio2Input

result = localize(Kio2Input(target_script="app.py", functions=["compute"]))
print(result.status, result.suspect_lines[0].line)
```

---

## 5. Docker

```bash
docker build -t ai4sweng-kio2 .
docker run -p 8013:8013 ai4sweng-kio2
# then: curl -XPOST localhost:8013/execute -H 'content-type: application/json' -d '{"payload":{}}'
```

The image installs FocusTracer from source (build arg `FOCUSTRACER_REF`, default
`git+https://github.com/BitnetTR/focustracer@main`) then the KIO2 package. For
offline builds, replace the git install with a `COPY` of a local FocusTracer
checkout. Env: `KIO_PORT` (default 8013), `KIO_HOST`.

> Note: the runner executes the target program to capture its trace, so the
> **target code must be reachable inside the container** — mount the repo under
> analysis as a volume, or pass a `working_directory` that exists in the image.
> The bundled dummy example is self-contained and works out of the box.

---

## 6. Integrating KIO2 into the general (platform) repo

KIO2 is written to drop into the AI4SWENG platform with **no code changes**:

- `service.make_app()` first tries `from kio_base import make_kio_app` (the
  platform's shared shell factory). If found, KIO2 becomes a **full KIO shell**:
  HTTP `/execute` **and** NATS JetStream transport, `CAPABILITY_ANNOUNCEMENT`,
  heartbeats, and HITL gating — automatically. If `kio_base` is absent (the
  standalone KIO2 repo), it falls back to the minimal FastAPI app with the same
  `/execute` contract.
- **Placement**: drop `src/kio2/` where the platform expects a shell, or run the
  image as its own service. KIO2 replaces the platform's placeholder `kio2`
  (which was a dummy "Planning Agent"); the real D2.6 KIO2 is this localizer.

### Two integration caveats (flag in the PR)

1. **The placeholder `kio2` was the pipeline *planner*.** The orchestrator's
   workflow engine reads `kio_sequence` from `kio2` to decide which KIOs run
   (`graph_nodes.py`: *"kio1 (Router) and kio2 (Planner) use this…"*). Our KIO2
   returns a **fault-localization** artifact, not a pipeline plan — so pipeline
   *planning* must move to KIO1 (or another stage). This is a coordination point,
   not a KIO2 defect.
2. **Dashboard progress.** The platform dashboard renders `TASK_PROGRESS` from
   each KIO's `publish_progress` calls. The KIO2 handler does not yet emit these
   (see §8 gaps) — add `publish_progress` at the trace/slice/done stages so the
   dashboard shows live progress; the localization artifact already renders in
   the artifact view.

---

## 7. Observability → Grafana: what's done

KIO2 is **instrumented** (`observability.py`). It emits to the **global**
OpenTelemetry providers; the host environment wires the exporter — KIO2 never
configures one itself, by design.

**Span** (per run): `kio2.localize` — attributes `kio2.session_id`,
`kio2.target`, `kio2.status`, `kio2.confidence`, `kio2.suspect_count`.

**Metrics** (meter `kio2`), each with a `status` attribute:

| Instrument | Type | Unit |
|---|---|---|
| `kio2.localization.duration` | histogram | ms |
| `kio2.localization.suspect_count` | histogram | 1 |
| `kio2.localization.confidence` | histogram | 0..1 |
| `kio2.localization.runs` | counter | 1 |

If `opentelemetry` is not installed, every emission is a **no-op** — the service
runs unchanged with or without the observability stack. The integration seam is
`observability.localization_span(session_id, target)`, which the handler already
wraps around each run.

## 7b. Observability → Grafana: what's still needed (gaps)

1. **Install + bootstrap the OTEL SDK.** Add `opentelemetry-sdk` +
   `opentelemetry-exporter-otlp` (the `observability` extra) and configure a
   `TracerProvider`/`MeterProvider` with an OTLP exporter pointing at the program
   collector — via standard env (`OTEL_SERVICE_NAME=kio2`,
   `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES`). This is owned by
   the program-wide observability agent (see `src/kio2/OTEL_HANDOFF.md`).
2. **Metric-name alignment (action needed).** The program collects metrics under
   the `kio.*` convention, and the KIO2-relevant one is **`kio.slicing.success_rate`**
   (WP3 target ≥ 0.85). KIO2 currently emits `kio2.localization.*`. **To feed real
   data**, KIO2 should additionally emit `kio.slicing.success_rate` (a per-run
   success signal = "was the fault isolated"), so the collector aggregates a real
   rate instead of the simulated 0.75–0.97 placeholder.
3. **Out of KIO2's scope (clarification).** The other program metrics —
   `kio.bugfix.duration_hours`, `kio.issue.resolution_hours`,
   `kio.issue.customer_reported_count` — are derived from issue trackers / pilot
   sprints, **not** from KIO2's runtime. KIO2 does not (and should not) emit them.
4. **Wire OTEL into `main.py` / Dockerfile** once the collector endpoint is fixed.

### KPI mapping (D1.1)

| KPI / metric | Source | KIO2 emits? |
|---|---|---|
| WP3 — Dynamic slicing success rate (≥ 0.85) → `kio.slicing.success_rate` | KIO2 runtime | **yes (to add, see gap #2)** |
| KPI 6.1 Bug-fix time → `kio.bugfix.duration_hours` | issue tracker / sprints | no (program-side) |
| KPI 1.2 Issue resolution → `kio.issue.resolution_hours` | issue tracker | no (program-side) |
| KPI 6.2 Customer-reported → `kio.issue.customer_reported_count` | evaluation sprints | no (program-side) |

---

## 8. Requirements mapping (D2.6)

| FR | Meaning | KIO2 component | Status |
|---|---|---|---|
| FR-KIO2-07 | Trace recorder | FocusTracer (dep) + `runner.py` | ✅ |
| FR-KIO2-02 | Trace Capture & Replay (forward/backward navigation) | FocusTracer `replay`/`reverse` | ✅ |
| FR-KIO2-04 | Post-mortem expression evaluator | FocusTracer state inspection | 🟡 partial |
| FR-KIO2-05 | AI Fault Localisation | `localizer.py` | ✅ (service core) |
| WP3 | Dynamic slicing success rate ≥ 0.85 | slicing + metric | ✅ (metric name to align) |

Per-requirement specs live in `docs/requirements/FR-KIO2-XX.md` (issue-template
format).

---

## 9. Testing

```bash
pip install -e path/to/focustracer      # engine
pip install -e .                        # KIO2 service
pytest -q                               # tests/test_kio2.py
```

Tests cover: fault line found on the dummy, evidence ranking, dummy fallback,
handler → KIO contract mapping, FAILED path for an untraceable target.

---

## 10. Known gaps / next steps

- **FR docs** for FR-KIO2-07 / 02 / 04 (code exists; specs to be written).
- **KIO11 input contract** — agree the `failing_test → Kio2Input` shape jointly
  with KIO11 owners; replace the dummy with real upstream input.
- **OTEL** — emit `kio.slicing.success_rate`, install/bootstrap the SDK, wire the
  collector (with the observability agent).
- **Platform** — add `publish_progress` for dashboard progress; confirm where
  pipeline planning moves after replacing the placeholder `kio2`.
- **FR-KIO2-04** — deepen the post-mortem expression evaluator (currently state
  inspection only).
