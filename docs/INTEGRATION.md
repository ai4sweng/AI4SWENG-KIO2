# KIO2 — Integration Guide

For whoever wires KIO2 into the AI4SWENG platform (KIO1 orchestrator) or calls
it from another KIO. Everything here is verified against the code in this
repository; where D2.6 and the implementation disagree, that is called out
explicitly rather than smoothed over.

- **What KIO2 does:** turns a *failing execution* into **ranked suspect
  statements** with runtime evidence, and lets a caller navigate or compare the
  recorded executions afterwards.
- **How it is reached:** one `POST /execute` that speaks **both** the KIO1
  dispatch protocol (§3) and KIO2's own contract (§5).
- **What it is not:** it does not generate a fix (per UC-UC1-03 that is KIO7 —
  but see §8, D2.6 is not consistent on this point).

---

## 1. Deployment

KIO2 is a **containerised HTTP service** with no UI of its own, matching D2.6's
microservice model (NFR-KIO1-03, *"scale horizontally across all KIO services"*)
where KIO1 owns the GUI/CLI.

| Mode | How | When |
|---|---|---|
| Docker service | `docker build -t ai4sweng-kio2 .` → `docker run -p 8102:8102 ai4sweng-kio2` | default for the platform; the image listens on **8102**, the port KIO1's dispatch registry has for KIO2 |
| Standalone process | `python -m kio2.main` | local development |
| Platform KIO shell | drop `src/kio2/` where the platform expects a shell | `make_app()` auto-detects `kio_base` and upgrades to NATS + HITL + capability announcements |
| Python library | `from kio2 import localize, replay, compare` | tests, notebooks, another KIO in-process |

Environment: `KIO_PORT` (**8102** in the image, `8013` for a bare local run),
`KIO_HOST`, `KIO2_TRACE_BUDGET` (default `45` s), `KIO2_TRACE_DIR` (default: the
system temp directory).

> **Not yet verified:** the Docker image has never been built end to end (no
> Docker daemon available during development). Build it once before relying on
> it. The `Dockerfile` installs FocusTracer from
> `git+https://github.com/BitnetTR/focustracer.git@master`.

### Dependency

KIO2 consumes **FocusTracer ≥ 1.9** as a library — an independent repository, not
vendored here. An older engine fails at import time; the dependency is pinned.

---

## 2. Two protocols, one endpoint

`POST /execute` answers **either** envelope, told apart by the shape of the body:

| Caller | Body has | Protocol |
|---|---|---|
| **KIO1 orchestrator** | `workflow_id` / `step_id` / `capability` / `task` / `endpoint` | KIO1 dispatch protocol → §3 |
| Anything else | `session_id` / `payload` | KIO2's own contract → §4 |

One path because that is what KIO1's `config.json` registers, and neither
contract constrains the other. Detection is deliberately generous: a KIO1
message *missing* `capability` is still recognised as KIO1's and answered with a
real error, rather than falling through and quietly localising the dummy example.

---

## 3. KIO1 dispatch protocol

Matches `kio1.orchestrator/docs/connecting-a-kio.md`. Implemented in
`src/kio2/kio1.py`, which is a pure translation layer — the domain modules know
nothing about KIO1.

### 3.1 Registration

```json
"KIO2": {
    "endpoint": "http://127.0.0.1:8102",
    "path": "/execute",
    "capabilities": ["bug_localization", "diagnosis", "replay", "trace_alignment"]
}
```

Two changes from what is in KIO1's config today:

- **`fix_recommendation` removed.** KIO2 localises; per D2.6 UC-UC1-03 the fix
  patch is KIO7's step. Asking KIO2 for it returns `status: "error"` with a
  message pointing at `diagnosis` (whose `slice_context` is exactly what KIO7
  needs) — an explicit refusal rather than a plausible-looking guess. See §8.
- **`replay` and `trace_alignment` added**, so KIO1 can drive a post-mortem
  debugging session and compare runs, not just ask one question.

`GET /tasks` returns the live list in both vocabularies (`capabilities` for KIO1,
`supported_tasks` for KIO2's own contract), plus `unsupported_capabilities`.

**Port: 8102.** That is what KIO1's `config.json` registers for KIO2, and it
follows the orchestrator's per-KIO scheme (KIO2 → 8102, KIO10 → 8110). The image
listens there. The *host* part depends on the topology: `http://127.0.0.1:8102`
for a single machine, `http://kio2:8102` where the service name resolves, e.g.
under Compose. KIO2's bare local default remains `8013`; `KIO_PORT` selects any
of them.

### 3.2 What to send

```json
{
  "workflow_id": "wf-bug-pay01",
  "step_id": "s2",
  "agent_id": "KIO2",
  "capability": "bug_localization",
  "endpoint": "http://127.0.0.1:8102",
  "task": "Locate the fault behind test_bronze_tier",
  "data": {
    "repository": { "path": "/work/repo", "revision": "a1b2c3d" },
    "target":     { "entry_point": "reproduce.py", "functions": [] },
    "failure":    {
      "test_id": "tests/test_order.py::test_bronze_tier",
      "exception_type": "KeyError",
      "message": "'bronze'"
    }
  }
}
```

`data` is the protocol's extension point, so everything structured lives there:

| `data` field | Required | Meaning |
|---|---|---|
| `target.entry_point` | **yes** (for localization/diagnosis) | runnable script; relative to `repository.path`. Also accepted as `data.entrypoint` |
| `repository.path` | recommended | repo root — also the scope for target discovery. Also accepted as `data.source_location` |
| `target.functions` | no | leave empty and KIO2 discovers them |
| `failure.*` | no | recorded as context; `test_id`, `exception_type`, `message`. Also accepted as `data.bug_report` (string or object) |
| `criterion` | no | `[FILE:]LINE[:VAR]` to analyse a value instead of the crash |
| `reference.trace_ref` | no | a passing run to diagnose against (see `diagnosis`) |
| `trace_ref` / `trace_refs` | for `replay` / `trace_alignment` | which recordings to work on. Also accepted as `data.execution_trace` |
| `seq`, `at_line`, `at_exception`, `step`, `step_action`, `back`, `window` | no | cursor controls |
| `upstream` | filled by KIO1 | dependency outputs; KIO2 reads `entry_point`, `target_script` and `trace_ref` out of them |

Because `upstream` is searched, a chain works with no extra wiring: whatever the
KIO11 step returned is available to KIO2's step, and a `trace_ref` from an
earlier KIO2 step is picked up automatically.

### 3.3 What comes back

Always HTTP **200**, always with `status` set explicitly (KIO1 reads a missing
`status` as success):

```json
{ "workflow_id": "wf-bug-pay01", "step_id": "s2", "agent_id": "KIO2",
  "status": "ok", "output": { … }, "error": null }
```

**`bug_localization`** — `summary` + `findings`, the shape KIO1's own reference
stub returns:

```json
{
  "summary": "Located the fault at shop/pricing.py:11 (discounted).",
  "verdict": "defect",
  "defect_found": true,
  "findings": [
    { "file": "shop/pricing.py", "function": "discounted", "line": 11,
      "confidence": 0.85, "score": 1.0, "dependency": "criterion",
      "description": "rate = {\"gold\": 0.20, \"silver\": 0.10}[tier]" },
    { "file": "shop/orders.py", "function": "order_total", "line": 9,
      "confidence": 0.425, "score": 0.5, "dependency": "data",
      "description": "return discounted(net, tier)" }
  ],
  "crash_state": { "net": "230", "tier": "'bronze'" },
  "criterion": "exception@pricing.py:11",
  "slice_size": 6,
  "confidence": 0.85,
  "trace_ref": "kio2://trace/QzpcVXNlcnN…",
  "hitl_required": false
}
```

Per-finding `confidence` is the run's confidence weighted by that statement's
evidence strength (`criterion` 1.0 > `control` 0.75 > `data` 0.5), so the top
finding carries the run's confidence. `score` and `dependency` are kept alongside
for consumers that want the evidence itself.

`file` paths are **relative to `repository.path`**, POSIX-separated. Absolute
paths from inside KIO2's container are meaningless to KIO1 and would leak our
filesystem layout.

**One field to act on: `verdict`.** Every localization and diagnosis reply
carries `verdict` — `"defect"` (statements were implicated), `"clean"` (the
target ran to completion, nothing to localise) or `"inconclusive"` (analysed, but
nothing could be attributed — treat as needing review). A consumer should read
that rather than inferring an answer from the length of `findings`, and it means
**no consumer needs to know where KIO2 sits in the workflow**: a deployment step
reads it to decide whether to proceed, a fix step reads it to decide whether to
run, the orchestrator surfaces it.

**A clean run is a success, not an error.** When the target runs to completion
KIO2 answers `status: "ok"` with `defect_found: false` and an empty `findings`
list. An orchestrator step that asks KIO2 to check code has to be able to hear
*"nothing wrong here"*; reporting that as an error would fail every workflow over
healthy code. `diagnosis` behaves the same way, with `root_cause` saying that
there is no faulty statement to attribute.

**`diagnosis`** — the causal story plus the evidence, and `slice_context` for KIO7:

```json
{
  "summary": "Localised to discounted L11: rate = {…}[tier]  (6 suspect statement(s))",
  "root_cause": "discounted at shop/pricing.py:11 failed executing `rate = {…}[tier]`, with net=230, tier='bronze' in scope. Those values are produced by: order_total:8 net += net_price(it); …",
  "evidence": [
    { "kind": "recorded_value", "at": "shop/pricing.py:11", "detail": "tier = 'bronze'" },
    { "kind": "value_difference", "detail": "tier: 'bronze' here vs 'gold' in the reference run" }
  ],
  "compared_runs": 2,
  "slice_context": "<value-annotated slice, ready for a fix prompt>",
  "confidence": 0.85,
  "trace_ref": "kio2://trace/…",
  "hitl_required": false
}
```

`root_cause` is read off the recording, not inferred by a model — KIO2 is not the
LLM in this pipeline. Pass `data.reference.trace_ref` (a passing run) and
`compared_runs` becomes 2 with divergence and value-difference evidence added.

**`replay`** — `cursor`, `total`, `can_forward`, `can_back`, `current`
(`{function, file, line, source, depth, state}`), `timeline`, `def_of`,
`trace_ref`. Stateless: send the returned `cursor` back as `data.seq`.

**`trace_alignment`** — `mode: "pair"` gives `distance`, `normalized_distance`,
`matched`, `gaps`, `aligned`, `delta`, `divergences`; `mode: "set"` (three or
more traces) gives `matrix`, `lengths`, `reference`, `outlier`, `mean_distance`
and `reference_trace_ref` / `outlier_trace_ref`.

### 3.4 `trace_ref`

Localization and diagnosis return a `trace_ref` (`kio2://trace/<encoded>`); the
replay and alignment capabilities take it back. It is an encoded path rather than
a raw one, so nothing about KIO2's filesystem crosses the boundary, and it is
**stateless** — any KIO2 replica that can see the same trace directory resolves
the same ref, which an in-memory registry could not do.

Refs are only resolved under `KIO2_TRACE_DIR` (default: the system temp
directory). The adapter is the network edge, and without that check a crafted ref
could make KIO2 parse an arbitrary file and return its contents as "recorded
state". Bare paths are still accepted from local/library callers.

### 3.5 Timing and tracing

- **Recording budget.** KIO1 waits `dispatch.request_timeout` (60 s) and does not
  retry. KIO2 caps recording at `KIO2_TRACE_BUDGET` seconds (default **45**), so
  it answers with an error inside the window instead of being abandoned mid-trace.
  Raise both together if you raise KIO1's.
- **`traceparent`.** The incoming W3C header is adopted, so KIO2's spans join
  KIO1's trace. Not yet verified against a live collector — OpenTelemetry is not
  installed in the development environment, where it is a no-op.
- **Concurrency.** Handled: work runs in a worker thread. Size the deployment for
  it, since each localization executes a whole program.

### 3.6 Smoke test

```bash
curl http://127.0.0.1:8102/health
curl -X POST http://127.0.0.1:8102/execute -H 'Content-Type: application/json' -d '{"workflow_id":"wf-test","step_id":"s1","agent_id":"KIO2","capability":"bug_localization","endpoint":"http://127.0.0.1:8102","task":"test","data":{"repository":{"path":"/work/repo"},"target":{"entry_point":"reproduce.py"}}}'
```

Expect `status: "ok"` and `output.findings`. Omit `data` and you should get
`status: "error"` naming the missing entry point — that is the correct answer,
not a malfunction.

---

## 4. Endpoints

| Method / Path | Purpose |
|---|---|
| `POST /execute` | JOB_REQUEST → JOB_RESULT |
| `GET /health/` | liveness + whether OpenTelemetry is active |
| `GET /tasks` | capability discovery — the same list the platform shell announces |

### Envelope

Request:

```json
{ "session_id": "abc-123", "payload": { "task_type": "...", "...": "..." } }
```

Response:

```json
{
  "message_id": "<uuid>",
  "session_id": "abc-123",
  "source": "kio2",
  "message_type": "JOB_RESULT",
  "payload": {
    "status": "DONE",
    "artifact_id": "<uuid>",
    "artifact_data": { "kio": "kio2", "...": "..." },
    "message": "human-readable summary"
  }
}
```

`payload.status` is one of:

| Status | Meaning | Extra fields |
|---|---|---|
| `DONE` | succeeded | — |
| `REVIEW_REQUIRED` | succeeded but low confidence → HITL gate | `hitl_question` |
| `FAILED` | could not complete | `error.{error_code, error_message, retryable}` |

`retryable` is always `false` today: every failure is deterministic (bad path,
untraceable target, unusable trace), so retrying the same request cannot help.

---

## 5. KIO2's own contract — the three tasks

`task_type` selects the task. If it is omitted, it is inferred from the payload
shape — `trace_paths` ⇒ alignment, `trace_path` ⇒ replay, otherwise
localization — so a caller written against the original localization-only
contract keeps working unchanged.

### 5.1 `fault_localization` — where is the bug? (FR-KIO2-05)

The main entry point. Records the failing run, computes a backward dynamic
slice from the crash, and ranks the statements on that slice.

```json
{
  "task_type": "fault_localization",
  "target_script": "main.py",
  "working_directory": "/work/repo",
  "functions": [],
  "criterion": null,
  "failing_test": "test_order_total — KeyError: 'bronze'"
}
```

| Field | Required | Meaning |
|---|---|---|
| `target_script` | yes | entry point to execute, absolute or relative to `working_directory` |
| `working_directory` | recommended | repo root; used as cwd, project root, and the scope for target discovery |
| `functions` | no | which functions to instrument. **Leave empty** and KIO2 discovers them from the project |
| `criterion` | no | `[FILE:]LINE[:VAR]` to analyse a specific value instead of the crash |
| `failing_test` | no | free-text context from upstream. **Currently stored but not used** — see §5 |
| `detail` | no | trace detail, default `detailed` (required for slicing) |
| `schema_version` | no | trace schema, default `2.3` (slicing needs ≥ 2.3) |

Response `artifact_data`:

```json
{
  "kio": "kio2",
  "status": "DONE",
  "criterion": "exception@pricing.py:11",
  "suspect_lines": [
    {"rank": 1, "score": 1.0, "dependency": "criterion", "file": ".../pricing.py",
     "function": "discounted", "line": 11, "source": "rate = {\"gold\": 0.20, ...}[tier]"}
  ],
  "crash_state": {"net": {"value": "230", "type": "int"},
                  "tier": {"value": "'bronze'", "type": "str"}},
  "slice_size": 6,
  "confidence": 0.85,
  "handoff_context": "<value-annotated slice, ready to paste into a fix prompt>",
  "trace_path": "/tmp/kio2_<id>.xml"
}
```

- **Ranking**: `criterion` (the crashing statement) = 1.0 > `control` = 0.75 >
  `data` = 0.5, de-duplicated by `file:line`.
- **`confidence`** is 0.85 when the crashing statement itself was identified,
  0.55 otherwise, minus 0.1 for a slice over 25 statements. Below 0.6 the status
  becomes `REVIEW_REQUIRED`.
- **`trace_path`** is the recording. Keep it — the other two tasks take it as
  input, and it is how a UI offers "step through this failure".
- **`handoff_context`** is the slice rendered as text with the recorded values
  attached. This is what KIO7 needs; it is *not* a patch.

### 5.2 `replay` — walk through the recorded failure (FR-KIO2-02)

Post-mortem debugging over a trace that already exists. Read-only: nothing is
re-executed, so what you see is exactly what was recorded.

**Stateless.** Keep the returned `cursor` and send it back as `seq` on the next
call. There is no server-side session, so any replica can serve any step.

```json
{ "task_type": "replay", "trace_path": "/tmp/kio2_<id>.xml",
  "at_exception": true, "step_action": "out", "window": 3, "def_var": "tier" }
```

Start point — first one set wins, default is the start of execution:
`seq` · `at_event` · `at_line` (+ `function` to disambiguate) · `at_exception`.

Movement: `step` (signed line count, `+3` forward / `-3` back), and
`step_action` = `into` | `over` | `out` with `back: true` for reverse execution.

Returns `cursor`, `total`, `can_forward`, `can_back`, `current`
(`{function, file, line, source, depth, state}` where `state` is
`{name: {value, type}}`), a `timeline` window for a scrubber, and `def_of` when
`def_var` was given.

### 5.3 `trace_alignment` — why did this run differ? (FR-KIO2-03)

Two traces, or a set of them.

```json
{ "task_type": "trace_alignment",
  "trace_paths": ["/tmp/failing.xml", "/tmp/passing.xml"], "seq": 3 }
```

**Two paths → `mode: "pair"`.** Returns `distance` / `normalized_distance` /
`matched` / `gaps`; a side-by-side cursor (`a_seq`, `b_seq`, `aligned`, and the
two cursor views `a` and `b`, driven by the same fields as `replay`); `delta` —
the variables whose *recorded values* differ at the aligned point; and
`divergences` — contiguous regions where only one run executed statements.

**Three or more → `mode: "set"`.** Returns `matrix` (symmetric pairwise
distances, zero diagonal), `lengths`, `reference` (the medoid — the most
representative run), `outlier` (furthest from the reference) and
`mean_distance`.

> **The distance compares control flow**, not data: traces are tokenised as the
> executed `function:line` sequence. Two runs that take the same path with
> different inputs have distance **0** — that difference shows up in `delta`.
> Identical traces always have distance 0 (the FR-KIO2-03 invariant).

Useful pattern for an orchestrator: record the failing run **and** a passing
run, put both plus any other captures into one `set` call, and the failing run
comes back as the `outlier` — with no labels supplied.

---

## 6. Operational notes

These are not defects but they will bite a long-running deployment.

**KIO2 executes the code under analysis.** Localization runs the target program
in a subprocess (that is the only way to obtain a runtime trace). Whoever
deploys KIO2 is therefore running untrusted repository code inside the KIO2
container. Treat the container as a sandbox: no credentials in its environment,
no write access to shared volumes beyond the repo under analysis, and network
egress restricted. This is a deployment decision, not something KIO2 can
enforce for you.

**The target code must be reachable inside the container.** Mount the repo under
analysis as a volume and pass its in-container path as `working_directory`. The
bundled dummy example is self-contained and needs no mount.

**Traces are never deleted.** Each localization writes
`<system temp>/kio2_<uuid>.xml` and returns the path, because the replay and
alignment tasks need it afterwards. Nothing cleans them up. Add a retention
policy (a cron sweep, a tmpfs with a size cap, or an explicit lifetime owned by
the orchestrator) before running KIO2 continuously.

**Timeout.** Tracing gives up after 180 s and returns `FAILED`. A long-running
target will not complete; scope it with `functions` or a smaller entry point.

**Concurrency.** The handler runs the blocking work in a worker thread
(`asyncio.to_thread`), so the service stays responsive, but each localization
spawns a subprocess that executes a whole program. Size the pool accordingly.

---

## 7. What the integration still needs a decision on

**The input mismatch — the one real blocker.** D2.6 UC-UC1-03 (p.83) says
KIO2's input is *"failing test results or runtime logs"*, handed over after
KIO11 confirms the failure. KIO2 accepts a **runnable entry point**
(`target_script` + `working_directory`). Nothing in the platform maps one to the
other today, and the `failing_test` field is accepted but unused.

Someone has to own that mapping. Three options:

1. **KIO1/KIO11 resolves it** — the orchestrator turns a failing test id into an
   entry point (e.g. `pytest <nodeid>` wrapped in a runner script) and calls KIO2
   with that. Cleanest: KIO2 stays a pure execution-tracing service.
2. **KIO2 grows a test-runner adapter** — accept `failing_test` as a pytest node
   id and build the entry point internally. Convenient, but pulls test-framework
   knowledge into KIO2.
3. **A shared convention** — the platform always provides a repo-local
   `reproduce.py`, and KIO2 traces that.

Recommend option 1, and until it is agreed, callers must supply
`target_script` themselves.

---

## 8. Where D2.6 and this implementation disagree

Recorded so it is visible during integration rather than discovered later. Page
references are to *D2.6 — Functional and non-Functional Requirements*.

**KIO2's role is described three different ways.** This implementation follows
UC-UC1-03 (localize, hand off to KIO7). That matches one of five references:

| Reference | What KIO2 does there |
|---|---|
| p.83, UC-UC1-03 | localises; **KIO7** proposes the fix ← **what we built** |
| p.37, KIO2 section | *"localisation **and remediation**"* → fixing is KIO2's |
| p.91, UC-UC3-02 | *"validates and refines code generated by KIO7"*, and checks KIO8's compilation metrics → a code reviewer |
| p.99, UC-UC5-05 | *"KIO1 runs KIO2 to locate **and fix** error(s)"* |
| p.100 | *"KIO2, responsible for bug locating **& fixing**"* |

The KIO chains (p.80–81) agree with the second reading, not the first: in
**all four** use-cases that involve KIO2, it comes **after** KIO7 —
`UC1: … KIO7 → KIO12 → KIO9 → KIO11 → KIO2 → KIO8`,
`UC3: … KIO7 → KIO8 → KIO2`, `UC4: … KIO7 → KIO10 → KIO11 → KIO2`,
`UC5: … KIO7 → KIO2`. UC-UC1-03's own sequence has KIO2 → KIO7. Both cannot be
right.

**Impact on integration:** if the orchestrator is built from the chains, it will
call KIO2 *after* KIO7 and expect a verdict on generated code. KIO2 returns a
fault localization, not a verdict. Agree the direction before wiring.

**UC3 cannot use KIO2 as built.** UC-UC3-02 (p.91) requires
`FR-KIO2-01, 02, 03, 04, 06, 07`, and UC3 is FPGA **C++/HLS** (p.81).
FR-KIO2-01 permits *"Python and/or C"*; the PoC decision was **Python only**.
The tracing engine is a Python-runtime instrumenter and has no C++/HLS path, so
UC3's KIO2 involvement is out of scope until either C support is planned or UC3's
KIO2 requirements are revised.

---

## 9. Smoke test after deployment

```bash
curl http://localhost:8013/health/
curl http://localhost:8013/tasks

# bundled failing example — no mounted repo needed
curl -XPOST http://localhost:8013/execute \
  -H 'content-type: application/json' -d '{"payload":{}}'
```

Expect `status: "DONE"` and a `suspect_lines[0]` on the division line of
`buggy_order_total.py`. If that works, the service and the engine are wired
correctly; anything further depends on the repo under analysis being mounted.

---

## 10. Observability

`observability.py` emits to the **global** OpenTelemetry providers and never
configures an exporter — the host wires OTLP via standard env vars
(`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES`).
With OpenTelemetry absent, every emission is a no-op.

- Spans: `kio2.localize`, `kio2.replay`, `kio2.trace_alignment`
- Metrics: `kio2.localization.{duration,suspect_count,confidence,runs}` and
  `kio2.task.{duration,runs}` (the latter tagged with `task_type`)

Still open: emitting the programme-wide `kio.slicing.success_rate`, and
`publish_progress` calls so the platform dashboard shows live progress. See
`src/kio2/OTEL_HANDOFF.md` and `docs/TECHNICAL_DOCUMENTATION.md` §7b.

---

## 11. The published schema

The request and response contracts ship as JSON Schema (draft 2020-12) rather
than being described only in prose, so the orchestrator can validate against them
instead of reproducing the shapes by hand:

| Where | What |
|---|---|
| `GET /schema` | both schemas, keyed `request` / `response` |
| `GET /schema?name=response` | one of them |
| `src/kio2/schemas/*.json` | the same files, in the repository |
| `GET /tasks` → `schema_url` | how a caller discovers the above |

These are an **enforced** contract, not documentation: the test suite validates a
real reply from every capability — including both error paths — against
`kio2.response.schema.json`, so the schema cannot drift from the implementation
without a test failing.

The request schema is published for the caller's benefit and is **not** applied
to inbound messages. KIO2's runtime acceptance is deliberately more lenient: it
honours the field-name aliases below and inherits missing values from
`data.upstream`, so a protocol change on KIO1's side does not take KIO2 down. A
message that fails the request schema may therefore still be served.

---

## 12. Field-name aliases

The *KIO1 – KIO2 Integration Strategy and Communication Protocol* document uses
its own names for the `data` payload. Both vocabularies are accepted, so the
wording of that document does not have to be settled before wiring can start:

| Integration document | KIO2 canonical | Note |
|---|---|---|
| `source_location` | `repository.path` | repo root |
| `entrypoint` | `target.entry_point` | the runnable script — **the document has no field for this yet**; see §7 |
| `execution_trace` | `trace_ref` | a recording produced by an earlier KIO2 step |
| `bug_report` | `failure` | accepted as a string or an object |
| `source_artifact` | — | recorded for traceability; KIO2 needs a path, not a name |
