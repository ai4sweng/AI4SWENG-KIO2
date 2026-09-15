# KIO2 — Technical Documentation

**KIO2 — Bug Locate & Fix: Reverse Execution & Dynamic Slicing**
Owner: BitNet · AI4SWENG · Status: v1.0.6 (localization + replay + trace alignment,
reachable over both KIO2's own contract and the KIO1 dispatch protocol)

> **Integrating KIO2 into the platform? Start with**
> [`docs/INTEGRATION.md`](INTEGRATION.md) — endpoints, the three task payloads,
> operational caveats, the open input-contract decision, and where D2.6 and this
> implementation disagree. This document is the *how it works* reference.

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
`handoff_context` for KIO7 to consume. In the program pipeline (D2.6 UC-UC1-03,
p.83): **KIO11 confirms the failure → KIO2 localizes → KIO7 fixes → HITL approves.**

> **This reading is contested.** Four other places in D2.6 (p.37, p.91, p.99,
> p.100) assign fixing or code-verification duties to KIO2 itself, and all four
> KIO chains (p.80–81) place KIO2 *after* KIO7. We built to UC-UC1-03; the
> discrepancy needs a consortium decision before the orchestrator is wired.
> Details: [`INTEGRATION.md`](INTEGRATION.md) §8.

The trace/slicing/replay engine underneath is **FocusTracer**, an independent
tool consumed here as a **library dependency** (not vendored). KIO2 is the
AI4SWENG service that wraps FocusTracer behind the KIO contract.

Every trace FocusTracer records and KIO2 reads back is an instance of one
schema, documented independently of this service in
[`docs/trace-schema/`](trace-schema/): format reference, version history, and
how to validate a trace file against it.

---

## 2. Architecture

```
                    ┌───────────────────────────── KIO2 service ──────────────────────────────┐
 failing target ──► │  runner.py ──► FocusTracer ──► trace.xml ──┐                              │
 (repo + entry)     │                  (engine)                  │                              │
                    │                                            ▼                              │
 other runs ───────►│                        ┌─── localizer.py ── slice → ranked suspects       │
 (same program)     │   trace set ──────────►├─── replayer.py  ── cursor → recorded state       │
                    │                        └─── comparator.py ─ distance · deltas · matrix    │
                    │                                            │                              │
                    │                                            ▼                              │
                    │  service.py ── KIO handler (/execute, task_type) ──► artifact             │
                    └────────────────────────────────────────────────────────────────────────┘
                                     │                                        │
                              observability.py                          → hand off to KIO7
                              (OTEL spans+metrics)
```

<!--
  Optional: replace or supplement the ASCII diagram above with a rendered
  architecture diagram, for example docs/architecture/kio2-architecture.png.
-->

`runner.py` is the only component that executes anything. Everything to its
right reads the recorded trace: `localizer.py` slices it (FR-KIO2-05),
`replayer.py` navigates it (FR-KIO2-02), `comparator.py` aligns several of them
(FR-KIO2-03).

### Package layers (`src/kio2/`)

| Module | Responsibility | FR | Platform-independent? |
|---|---|---|---|
| `contract.py` | input/output models for every task — the interface | — | yes |
| `runner.py` | run the target under FocusTracer → produce a trace (subprocess) | 07 | yes |
| `localizer.py` | **core**: trace → slice → ranked suspects + crash state + handoff | 05 | yes (only depends on FocusTracer) |
| `replayer.py` | **core**: post-mortem navigation over a recorded trace | 02 | yes |
| `comparator.py` | **core**: align traces / curate a trace set | 03 | yes |
| `observability.py` | optional OpenTelemetry spans/metrics (no-op if OTel absent) | — | yes |
| `kio1.py` | KIO1 dispatch-protocol adapter (envelope translation, capability mapping, `trace_ref`) | — | adapter |
| `service.py` | KIO handler + `make_app` (platform shell **or** standalone FastAPI) | — | adapter |
| `dummy.py` + `examples/` | bundled failing example for standalone runs | — | yes |
| `main.py` | service entrypoint (`uvicorn kio2.main:app`) | — | adapter |

The **core** (`localizer`, `replayer`, `comparator`, `runner`, `contract`,
`observability`) has no dependency on the AI4SWENG platform, so KIO2 runs
identically as a library call, a standalone API, or a platform KIO shell.

`replayer` and `comparator` are strictly **read-only over an existing trace** —
they never re-run the program. Only `runner` executes anything, and only to
capture the initial recording.

---

## 3. Input and Output

KIO2 serves **three task types** on one endpoint, selected by `task_type` in the
payload. When `task_type` is absent it is inferred from the payload shape
(`trace_paths` ⇒ alignment, `trace_path` ⇒ replay, otherwise localization), so
callers written against the original localization-only contract keep working.

| `task_type` | Input | Output | Requirement |
|---|---|---|---|
| `fault_localization` (default) | `Kio2Input` | `FaultLocalization` | FR-KIO2-05 |
| `replay` | `ReplayInput` | `ReplayView` | FR-KIO2-02 |
| `trace_alignment` | `AlignInput` | `TraceComparison` | FR-KIO2-03 |

### Input — `Kio2Input` (envelope `payload`)

| Field | Type | Meaning |
|---|---|---|
| `target_script` | str (required) | path to the failing script / entrypoint to trace |
| `working_directory` | str | repo root (used as cwd + project root) |
| `functions` | list[str] | trace targets; **empty ⇒ discovered from the project** (see below) |
| `criterion` | str \| null | `[FILE:]LINE[:VAR]`; `null` ⇒ localize at the crash |
| `failing_test` | str \| null | failing-test/error context (normally from KIO11; dummy for now) |
| `detail` | str | trace detail level (`detailed` required for slicing) |
| `schema_version` | str | trace schema (slicing needs ≥ `2.3`) |

A bare payload (no `target_script`) falls back to the bundled dummy example.

#### Trace-target discovery (why `functions` is optional)

KIO2's callers know *which run failed*, not *which functions to instrument* —
D2.6 specifies the input as failing test results or runtime logs, never a
function list. The engine, however, requires explicit function targets (file-only
activation is not supported), and its own trace-all fallback scans **the entry
script only**. A realistic entry point — a `main.py` that just calls into a
package — defines no functions, so that fallback finds nothing.

`runner.discover_functions()` closes the gap on the KIO2 side: when `functions`
is empty it statically collects every function and method defined under
`working_directory`, entry script first, skipping `.venv`, `__pycache__`,
`node_modules` and friends. Files that fail to parse are skipped, not fatal.

The list is capped at `MAX_AUTO_TARGETS` (400 — each target becomes a
`--function` flag and Windows caps a command line at ~32 000 characters).
Ordering puts the entry script and its siblings first, so a truncated list keeps
the code nearest the entry point; when truncation happens it is **reported** in
the result `message`, never silent. If no functions exist anywhere, the run fails
with an actionable error rather than an engine-level one.

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

### `replay` — `ReplayInput` → `ReplayView` (FR-KIO2-02)

Post-mortem navigation over a trace that was already recorded. **Stateless**: the
caller keeps the returned `cursor` and sends it back as `seq` on the next step,
so there is no server-side session to expire or to share between replicas.

| Field | Meaning |
|---|---|
| `trace_path` (required) | the recorded trace to navigate |
| `seq` / `at_event` / `at_line` (+`function`) / `at_exception` | where to place the cursor (default: start of execution) |
| `step` | signed line steps from that point (`+N` forward, `−N` backward) |
| `step_action` + `back` | debugger step `into` / `over` / `out`, optionally in reverse |
| `window` | how many neighbour line-events to return around the cursor |
| `def_var` | also report the statement that last defined this variable (def-use) |

Returns `cursor` / `total` / `can_forward` / `can_back`, `current` (the executed
statement plus the **recorded** state, `{name: {value, type}}`), a `timeline`
window for a scrubber, and `def_of` when `def_var` was given.

### `trace_alignment` — `AlignInput` → `TraceComparison` (FR-KIO2-03)

`trace_paths` carries two traces (`mode: "pair"`) or three and more
(`mode: "set"`). In pair mode the same cursor fields as `replay` drive trace A
while trace B follows through the alignment.

| `mode` | Returns |
|---|---|
| `pair` | `distance` / `normalized_distance` / `matched` / `gaps`; `aligned`, `a_seq`, `b_seq`, the two cursor views `a` and `b`; `delta` (variables whose recorded values differ at the aligned point); `divergences` (contiguous gap regions); `pairs` only when `include_pairs` is set |
| `set` | `matrix` (symmetric pairwise distances, 0 diagonal), `lengths`, `reference` (medoid — the most representative run), `outlier` (furthest from the reference), `mean_distance` |

The distance compares **control flow** (the executed `function:line` sequence),
so two runs that take the same path with different data have distance 0 — that
difference surfaces in `delta`. Identical traces always have distance 0 (the
FR-KIO2-03 invariant).

```json
{
  "status": "DONE", "mode": "pair", "distance": 5, "normalized_distance": 0.4545,
  "matched": 6, "gaps": 5, "aligned": true, "a_seq": 3, "b_seq": 3,
  "delta": [{"name": "factor", "a": "1", "b": "10"}],
  "divergences": [{"side": "b", "start": 1, "end": 6, "length": 5, "at": 0}],
  "message": "Distance 5 (normalized 0.455) — 5 divergent statement(s)."
}
```

---

## 4. API

The service exposes the KIO contract. Standalone it is a minimal FastAPI app;
inside the platform it is a full KIO shell (see §6).

| Method / Path | Purpose |
|---|---|
| `POST /execute` | JOB_REQUEST → JOB_RESULT (runs the payload's `task_type`) |
| `GET /health/` | liveness + `otel` flag |
| `GET /tasks` | capability discovery — in both vocabularies (`capabilities` for KIO1, `supported_tasks` for KIO2's own contract) |
| `GET /health` | same as `/health/`; the spelling KIO1's liveness probe uses |

> `POST /execute` also speaks the **KIO1 dispatch protocol** — a different
> envelope on the same path, told apart by the body shape. Full details in
> [`INTEGRATION.md`](INTEGRATION.md) §3.

### Examples

```bash
# health + capabilities
curl http://localhost:8013/health/
curl http://localhost:8013/tasks

# localize a specific target
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' \
  -d '{"session_id":"s1","payload":{"target_script":"/work/app.py","working_directory":"/work","functions":["compute"]}}'

# bare payload ⇒ bundled dummy example
curl -XPOST http://localhost:8013/execute -H 'content-type: application/json' -d '{"payload":{}}'

# replay: step into, from the crash, in the trace the localization produced
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' \
  -d '{"payload":{"task_type":"replay","trace_path":"/tmp/kio2_x.xml","at_exception":true,"step_action":"out"}}'

# alignment: compare two runs side by side at timeline index 3
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' \
  -d '{"payload":{"task_type":"trace_alignment","trace_paths":["/tmp/a.xml","/tmp/b.xml"],"seq":3}}'

# alignment: curate a set of runs (distance matrix + reference + outlier)
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' \
  -d '{"payload":{"trace_paths":["/tmp/a.xml","/tmp/b.xml","/tmp/c.xml"]}}'
```

### Library / one-shot use (no server)

Each task is also a plain function — same models, no transport:

```python
from kio2 import compare, localize, replay
from kio2.contract import AlignInput, Kio2Input, ReplayInput

# FR-KIO2-05 — locate the fault
result = localize(Kio2Input(target_script="app.py", functions=["compute"]))
print(result.status, result.suspect_lines[0].line)

# FR-KIO2-02 — walk out of the crashing frame and read the recorded state
view = replay(ReplayInput(trace_path=result.trace_path, at_exception=True, step_action="out"))
print(view.current["function"], view.current["state"])

# FR-KIO2-03 — why does this run differ from a passing one?
diff = compare(AlignInput(trace_paths=[result.trace_path, "passing.xml"], seq=view.cursor))
print(diff.distance, diff.delta)
```

---

## 5. Docker

```bash
docker build -t ai4sweng-kio2 .
docker run -p 8102:8102 ai4sweng-kio2
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

The `replay` and `trace_alignment` tasks emit a span named after the task
(`kio2.replay`, `kio2.trace_alignment`) plus two shared instruments carrying a
`task_type` **and** a `status` attribute, so post-mortem navigation (FR-KIO2-02)
and trace comparison (FR-KIO2-03) can be separated on the dashboards:

| Instrument | Type | Unit |
|---|---|---|
| `kio2.task.duration` | histogram | ms |
| `kio2.task.runs` | counter | 1 |

If `opentelemetry` is not installed, every emission is a **no-op** — the service
runs unchanged with or without the observability stack. The integration seams are
`observability.localization_span(session_id, target)` and
`observability.task_span(task_type, session_id, target)`, which the handler
already wraps around each run.

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
| FR-KIO2-02 | BITNET | Trace Capture & Replay: step into/over/out/back, state snapshots, def-use slice viz, post-mortem session | ✅ `core/replay.py` (`ReplaySession`), `core/reverse.py`, `core/slicer.py`, CLI `replay`/`reverse`/`slice`/`load`, GUI tabs (Step Into/Over/Out incl. reverse) | ✅ `replayer.py` + `replay` task on `/execute`; `tests/test_fr_kio2_02_replay.py` | ✅ **Satisfied** — DAP/LSP deferred (§8b) |
| FR-KIO2-03 | BITNET | Multi-trace alignment: bioinformatics-style sequence alignment, distance metric, trace-set curation | ✅ `core/align.py` — Needleman-Wunsch alignment, `trace_distance` (0 for identical), `divergences()`, `AlignedPair` side-by-side session, `TraceSet` (matrix / medoid / outlier), CLI `align` (3 modes), GUI Align tab | ✅ `comparator.py` + `trace_alignment` task on `/execute`; `tests/test_fr_kio2_03_alignment.py` | ✅ **Satisfied** for Objective / Input / Output / Invariant; the *Description*'s ML pipeline stays deferred (§8b) |
| FR-KIO2-04 | HESSO | Post-mortem expression evaluator (+ mocks for unrecorded data) | 🟡 state inspection only (`replay`/`reverse`) | ❌ | 🟡 **Partial** — no arbitrary-expression eval, no mock injection |
| FR-KIO2-05 | HESSO | AI fault localisation — ML anomaly detection over *sets* of traces | ❌ ML technique not built | ✅ slicing-based localisation (`localizer.py`) | 🟡 **Partial/divergent** — **pre-conditions now met** by FR-03 (distance defined + implemented, multi-trace replay) |
| FR-KIO2-06 | HESSO | AI-assisted (generative) mocking of external services | ❌ | ❌ | ❌ **Not started** |
| FR-KIO2-07 | BITNET | Trace recorder — every executed line, variable mutation, call; no manual code changes | ✅ `core/recorder.py` + `core/patcher.py`, schema v2.3 with `reads` (use-set) | ✅ `runner.py`; `tests/test_fr_kio2_07_trace_recorder.py` (state capture, replay-readability, semantics, reproducibility) | ✅ **Satisfied** |
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

**Honest summary.** All four BitNet-owned functional requirements — FR-01, FR-02,
FR-03, FR-07 — are **Satisfied**: the spine (record → replay/navigate → slice →
localize → align) is implemented in the engine, reachable through the KIO2
contract, and covered by per-requirement acceptance tests in this repo. What
remains on BitNet's side is **NFR-KIO2-01** (performance benchmarks and CI gates,
untouched) and the two empty Task specs. HESSO-owned FR-04/05/06 and NFR-02 are
still open, but FR-05's stated pre-conditions — *"the notion of distance between
traces is formally defined"*, *"the evaluation of trace distances is
implemented"*, *"the replay engine … supports interactions with multiple
execution traces simultaneously"* — are all **met** by FR-03, so FR-05 is
unblocked and its input (the pairwise distance matrix) is already produced.

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
pip install -e path/to/focustracer      # engine (needs >= 1.9 — see below)
pip install -e ".[dev]"                 # KIO2 service + pytest
ruff check .                            # lint (FR-KIO2-01 tooling)
pytest -q                               # tests/
```

> **Engine version matters.** KIO2 imports `focustracer.core.{slicer,reverse,explain}`
> (FocusTracer 1.5–1.6), `core.replay` / `core.align` (1.8), and `align.TraceSet` +
> `AlignedPair.seek/step/state_delta` (1.9). An older engine fails at import, so the
> dependency is pinned `focustracer>=1.9`.

| Test file | Covers |
|---|---|
| `tests/test_kio2.py` | fault line found on the dummy, evidence ranking, dummy fallback, handler → KIO contract mapping, FAILED path for an untraceable target |
| `tests/test_fr_kio2_01_language_support.py` | **FR-KIO2-01 acceptance** — a Python target produces an XSD-valid trace; instrumentation preserves semantics |
| `tests/test_fr_kio2_02_replay.py` | **FR-KIO2-02 acceptance** — step into/over/out, forward↔backward symmetry, jump-to-crash, def-use, replayed state == the localizer's recorded crash state, task routing over `/execute` |
| `tests/test_fr_kio2_03_alignment.py` | **FR-KIO2-03 acceptance** — distance 0 for identical runs (the invariant), symmetry, divergence accounting, side-by-side cursor + value deltas, trace-set matrix/reference/outlier, task routing |
| `tests/test_fr_kio2_07_trace_recorder.py` | **FR-KIO2-07 acceptance** — variable states captured with types, exception recorded, trace readable by the replay engine, recorded values match an untraced run, two recordings of one program are identical |
| `tests/test_http_contract.py` | the deployed surface — `/health/`, `/tasks`, and `/execute` for all three task types over the real ASGI app |
| `tests/test_kio1_protocol.py` | **the KIO1 dispatch protocol** — envelope echo, explicit `status`, HTTP 200 on task failure, the four capabilities, `trace_ref` hand-off between steps, the refusal of `fix_recommendation`, and that KIO2's own contract still works |
| `tests/test_target_discovery.py` | tracing a multi-module project with **no** `functions` given — discovery across modules, entry-point ordering, noise-directory skipping, truncation reporting, cross-module slice |

`tests/conftest.py` records one program under several inputs — that trace set is
what the FR-02/03/07 tests navigate, align and curate.

Engine-side coverage lives in the FocusTracer repo: `tests/test_replay.py`
(step into/over/out/back, depth mechanics), `tests/test_reverse.py` (exact state
reconstruction), `tests/test_align.py` (distance 0 for identical traces, gap
annotations, `TraceSet` matrix/medoid/outlier, address-insensitive value deltas),
`tests/test_gui_align.py` (the web API), `tests/test_slicer.py`.

**CI** — [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs `ruff check`
and `pytest` on every push and PR (Python 3.11 + 3.12), installing FocusTracer
from `git+https://github.com/BitnetTR/focustracer.git@master` first. This closes
the FR-KIO2-01 clause *"provide minimal tooling to build and run locally **and in CI**"*.

---

## 10. Known gaps / next steps

Ordered by ownership, so BitNet's queue is separable from partner work.

### BitNet-owned (the actionable queue)

1. **NFR-KIO2-01 (untouched)** — no benchmark harness, no p95 measurement, no
   ≤ 5 s gate, no perf job in CI. This is now the only fully unstarted BitNet item.
2. **Operational hardening before continuous use** (see
   [`INTEGRATION.md`](INTEGRATION.md) §8): trace files accumulate in the system
   temp directory with no retention policy; the service **executes the code under
   analysis**, so the container has to be treated as a sandbox; and the Docker
   image has never been built end to end.
3. **OTEL** — emit `kio.slicing.success_rate`, install/bootstrap the SDK, wire the
   collector (with the observability agent). See §7b.
4. **Task-KIO2-01 / 02** — both spec files are **empty**; the compliance and
   interoperability-standards analyses still have to be written.
5. **Trace-set persistence** — `TraceSet` curates a set that the caller assembles;
   there is no *stored* corpus with metadata (input, config, pass/fail label).
   FR-KIO2-05 and NFR-KIO2-02 will both want one, and the test-program corpus
   still lives outside this repo.
6. **Alignment cost at scale** — Needleman-Wunsch is O(n·m) per pair and a trace
   set is O(N²) pairs. Fine for PoC-sized traces; a long-running program will need
   banding or an anchor-based prefilter. Worth measuring under NFR-KIO2-01 before
   optimising.

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
- **KIO11 input contract (the one real integration blocker)** — D2.6 UC-UC1-03
  specifies KIO2's input as *"failing test results or runtime logs"*; KIO2 accepts a
  runnable entry point. Nothing maps one to the other, and `failing_test` is
  accepted but unused. Options + recommendation: [`INTEGRATION.md`](INTEGRATION.md) §7.
- **KIO2's role is described three different ways in D2.6**, and all four KIO
  chains place KIO2 *after* KIO7 rather than before it. Agree the direction before
  the orchestrator is wired: [`INTEGRATION.md`](INTEGRATION.md) §8.
- **UC3 (FPGA, C++/HLS) cannot use KIO2 as built** — it requires FR-KIO2-01..07,
  while the PoC decision was Python-only. Same section.
- **Platform** — add `publish_progress` for dashboard progress; confirm where
  pipeline planning moves after replacing the placeholder `kio2`.
