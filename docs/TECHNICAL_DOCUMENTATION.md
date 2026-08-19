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
`git+https://github.com/BitnetTR/focustracer.git@master`) then the KIO2 package. For
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

Covers all 13 items in [`docs/requirements/`](requirements/) — 8 FR, 3 NFR,
2 Tasks. Engine work lands in **FocusTracer** (independent repo); KIO2 is the
AI4SWENG service that exposes it. A requirement is only *Satisfied* when both
columns are green: the engine capability **and** the KIO2-side surface/test.

Legend: ✅ done · 🟡 partial · ❌ not started · ⛔ out of KIO2 scope

### Functional

| FR | Owner | Meaning (final D2.6) | Engine (FocusTracer) | KIO2 service | Status |
|---|---|---|---|---|---|
| FR-KIO2-01 | BITNET | Language support (Python PoC) + build/run/lint tooling locally and in CI | ✅ Python-only, zero-touch monkey-patching, XSD-valid traces | ✅ `pyproject` (ruff/pytest), `tests/test_fr_kio2_01_language_support.py`, `.github/workflows/ci.yml` | ✅ **Satisfied** |
| FR-KIO2-02 | BITNET | Trace Capture & Replay: step into/over/out/back, state snapshots, def-use slice viz, post-mortem session | ✅ `core/replay.py` (`ReplaySession`), `core/reverse.py`, `core/slicer.py`, CLI `replay`/`reverse`/`slice`/`load`, GUI tabs | 🟡 consumed indirectly by `localizer.py`; **no `replay` task on `/execute`**, no KIO2-side acceptance test | 🟡 **In progress** — engine done, service surface open |
| FR-KIO2-03 | BITNET | Multi-trace alignment: bioinformatics-style sequence alignment, distance metric, trace-set curation | ✅ `core/align.py` — Needleman-Wunsch `align_sequences`/`align_traces`, `trace_distance` (0 for identical), `AlignedPair` multi-trace cursor, CLI `align` | ❌ no `align` task on `/execute`, no trace-set store | 🟡 **In progress** — engine done; curation + service surface open; ML framing deferred (see §8b) |
| FR-KIO2-04 | HESSO | Post-mortem expression evaluator (+ mocks for unrecorded data) | 🟡 state inspection only (`replay`/`reverse`) | ❌ | 🟡 **Partial** — no arbitrary-expression eval, no mock injection |
| FR-KIO2-05 | HESSO | AI fault localisation — ML anomaly detection over *sets* of traces | ❌ ML technique not built | ✅ slicing-based localisation (`localizer.py`) | 🟡 **Partial/divergent** — **pre-conditions now met** by FR-03 (distance defined + implemented, multi-trace replay) |
| FR-KIO2-06 | HESSO | AI-assisted (generative) mocking of external services | ❌ | ❌ | ❌ **Not started** |
| FR-KIO2-07 | BITNET | Trace recorder — every executed line, variable mutation, call; no manual code changes | ✅ `core/recorder.py` + `core/patcher.py`, schema v2.3 with `reads` (use-set) | ✅ `runner.py` | 🟡 **Mostly done** — no KIO2-side acceptance test; test-program corpus lives outside this repo |
| FR-KIO2-08 | AI4 / UREAD | LLM-assisted live GDB debugging, HITL-gated | — | — | ⛔ **Out of KIO2 scope** — depends on all FR-KIO1 |

### Non-functional & tasks

| ID | Owner | Meaning | Status |
|---|---|---|---|
| NFR-KIO2-01 | **BITNET** | Performance: common ops ≤ 5 s, p95 thresholds, benchmark reports, CI/CD perf gates | ❌ **Not started** — no benchmark harness, no perf gate |
| NFR-KIO2-02 | HESSO | Accuracy: replay fidelity ≥ 95 %, fault-loc precision ≥ 85 % / recall ≥ 80 %, FPR ≤ 10 % | ❌ **Not started** — needs a labelled bug dataset |
| NFR-KIO2-03 | HESSO / BITNET | Modularity: module boundaries + APIs, containerisation, upgrade/rollback, dependency health | 🟡 **Partial** — layered package + `Dockerfile` ✅; API v1.x versioning, container registry, upgrade/rollback validation ❌ |
| Task-KIO2-01 | — | EU AI Act / EU Data Act / GDPR compliance check | ❌ **spec file empty** |
| Task-KIO2-02 | — | Identification of interoperability standards | ❌ **spec file empty** |
| WP3 KPI | BITNET | Dynamic slicing success rate ≥ 0.85 → `kio.slicing.success_rate` | 🟡 slicing ✅, metric name not yet emitted (see §7b gap 2) |

**Honest summary.** The KIO2 *spine* — record → replay/navigate → slice →
localize → align — is implemented in the engine (FR-01 ✅, FR-02/03/07 engine ✅).
What is open on **BitNet's** side is the **service surface** (FR-02/03 are not
reachable through `/execute`), **NFR-KIO2-01** (performance, untouched), and the
two empty Task specs. HESSO-owned FR-04/05/06 and NFR-02 remain open, but FR-05's
stated pre-conditions ("distance between traces formally defined and implemented",
"replay engine supports multiple traces simultaneously") are now **satisfied** by
FR-03, so FR-05 is unblocked.

### 8b. Scope decisions (recorded, not defects)

These are deliberate PoC-scope calls made while implementing FR-02/FR-03. They are
listed here so the requirement text and the delivery do not silently diverge.

| Decision | Requirement text | Call | Rationale |
|---|---|---|---|
| **DAP not implemented** | FR-KIO2-02 constraint: *"Must support standard Debug Adapter Protocol (DAP) **where possible**"* | Deferred beyond the PoC | `ReplaySession` provides full functional equivalence (into/over/out/back, state, def-use) through the Python API and CLI. A DAP server is an adapter over that API and can be added later without touching the engine. |
| **LSP jump-to-definition postponed** | FR-KIO2-02 behaviour: *"read-only source viewer supporting standard IDE features (syntax highlighting, jump to definition, …)"* | Viewer ✅, LSP ❌ | Syntax-highlighted read-only viewer ships in the GUI; language-server integration is IDE plumbing, not KIO2 debugging logic. |
| **FR-03 ML pipeline deferred** | FR-KIO2-03 *Description*: dataset curation, feature engineering, model selection/training, model registry/MLOps, privacy checks | Alignment delivered; ML deferred | FR-03's **Objective / Behaviour / Output / Invariant** all describe trace alignment + distance, which is what is built. The ML wording in *Description* overlaps FR-KIO2-05 (HESSO). **Action needed:** agree with HESSO whether that paragraph moves to FR-05 or FR-03 gains an ML work package — otherwise FR-03 can never be marked Satisfied. |
| **C dropped from FR-01** | FR-KIO2-01: *"Python and/or C"* | Python only | Explicit PoC constraint: *"Select one primary language (Python) for PoC."* |

---

## 9. Testing & CI

```bash
pip install -e path/to/focustracer      # engine (needs >= 1.8 — see below)
pip install -e ".[dev]"                 # KIO2 service + pytest
ruff check .                            # lint (FR-KIO2-01 tooling)
pytest -q                               # tests/
```

> **Engine version matters.** KIO2 imports `focustracer.core.{slicer,reverse,explain}`.
> Those arrived in FocusTracer 1.5–1.6; `replay`/`align` in 1.8. An older engine
> fails at import, so the dependency is pinned `focustracer>=1.8`.

| Test file | Covers |
|---|---|
| `tests/test_kio2.py` | fault line found on the dummy, evidence ranking, dummy fallback, handler → KIO contract mapping, FAILED path for an untraceable target |
| `tests/test_fr_kio2_01_language_support.py` | **FR-KIO2-01 acceptance** — a Python target produces an XSD-valid trace; instrumentation preserves semantics |

Engine-side coverage lives in the FocusTracer repo: `tests/test_replay.py`
(step into/over/out/back, depth mechanics), `tests/test_reverse.py` (exact state
reconstruction), `tests/test_align.py` (distance 0 for identical traces, positive
distance and gap annotations for divergent inputs), `tests/test_slicer.py`.

**CI** — [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs `ruff check`
and `pytest` on every push and PR (Python 3.11 + 3.12), installing FocusTracer
from `git+https://github.com/BitnetTR/focustracer.git@master` first. This closes
the FR-KIO2-01 clause *"provide minimal tooling to build and run locally **and in CI**"*.

---

## 10. Known gaps / next steps

Ordered by ownership, so BitNet's queue is separable from partner work.

### BitNet-owned (the actionable queue)

1. **FR-KIO2-02 / 03 service surface** — `/execute` advertises only
   `fault_localization` (`service.py::_SUPPORTED_TASKS`). Both requirements state
   *"Output: an API allowing a UI or a CLI to interact with the system"*. Add
   `replay` and `align` task types over `ReplaySession` / `align_traces`, plus
   KIO2-side acceptance tests.
2. **NFR-KIO2-01 (untouched)** — no benchmark harness, no p95 measurement, no
   ≤ 5 s gate, no perf job in CI. This is the only fully unstarted BitNet item.
3. **Trace-set curation** — FR-03 asks to *"lay down foundation to curate sets of
   execution traces"*; FR-05 consumes exactly that. Needs a trace-set layout +
   recording automation (the test-program corpus currently lives outside this repo).
4. **FR-KIO2-07 acceptance test** — recorder works, but nothing in `tests/` asserts
   the requirement's own criteria (variable states captured; trace machine-readable
   by the replay engine).
5. **OTEL** — emit `kio.slicing.success_rate`, install/bootstrap the SDK, wire the
   collector (with the observability agent). See §7b.
6. **Task-KIO2-01 / 02** — both spec files are **empty**; the compliance and
   interoperability-standards analyses still have to be written.

### Cross-partner / coordination

- **FR-03 scope conflict** — resolve the alignment-vs-ML-pipeline mismatch with
  HESSO (see §8b), otherwise FR-03 cannot be closed.
- **FR-KIO2-05 (HESSO, now unblocked)** — its pre-conditions are met; ML anomaly
  detection over trace sets is the remaining technique.
- **FR-KIO2-04 (HESSO)** — arbitrary-expression evaluator + mock injection on top
  of the existing state inspection.
- **FR-KIO2-06 (HESSO)** — generative mocking of external-service interactions.
- **NFR-KIO2-02 (HESSO)** — labelled bug dataset, replay-fidelity and
  precision/recall measurement.
- **NFR-KIO2-03** — API v1.x versioning policy, container registry,
  upgrade/rollback validation.
- **KIO11 input contract** — agree the `failing_test → Kio2Input` shape jointly
  with KIO11 owners; replace the dummy with real upstream input.
- **Platform** — add `publish_progress` for dashboard progress; confirm where
  pipeline planning moves after replacing the placeholder `kio2`.
