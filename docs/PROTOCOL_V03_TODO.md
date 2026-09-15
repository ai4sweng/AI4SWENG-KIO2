# What v0.3 of the integration protocol asks of KIO2

The *KIO1 – KIO2 Integration Strategy and Communication Protocol* was raised to
v0.3 (tracked changes, awaiting review). Most of it documents what the code
already does. Four items are written there as **proposed** and are not
implemented here yet. They are listed below in the order they matter for the
first integration.

---

## 1. Asynchronous processing for long analyses — the blocker

**Why.** KIO2 executes the program under analysis, so its runtime is the target's
runtime. Today that is bounded twice: KIO1 waits `dispatch.request_timeout`
(60 s) and does not retry, and `kio1.py` caps recording at `KIO2_TRACE_BUDGET`
(45 s) so it can still answer. `runner.py` allows 180 s on KIO2's own contract,
and a dispatched step cannot use it. Any repository whose reproduction takes
longer than 45 s is reported as a *failure* while KIO2 is working correctly.

**What to build.** The 202 + job pattern, identical to the one the KIO9 and KIO12
protocols already define, so a caller writes one mechanism for three agents:

- `POST /execute` returns **HTTP 202** with `status: "accepted"` and a `job`
  object (`job_id`, `status_uri`, `result_uri`, `retry_after_s`, `expires_at`)
  when the analysis does not fit the synchronous budget.
- `GET /jobs/{job_id}` → `{job_id, state, progress, retry_after_s, result_uri}`
  with `state` in `queued | running | completed | failed | cancelled | expired`.
- `GET /jobs/{job_id}/result` → the ordinary reply envelope, unchanged.
- `DELETE /jobs/{job_id}` → cancellation.
- Honour `Prefer: respond-async` / `respond-sync` and an optional `deadline`.
- Publish `sync_budget_s` and `max_duration_s` per capability in `GET /tasks`.

**Watch out for.** The job store has to survive a replica switch, which is the
same constraint `KIO2_TRACE_DIR` already has: either a shared directory or
sticky routing. Keep the synchronous path exactly as it is, so a v0.2 caller
sees no change.

## 2. Closed error vocabulary

**Why.** `AgentReply.error` is a free-text string today, so KIO1 cannot tell
"you sent no entry point" from "the target crashed the tracer" without parsing
prose.

**What to build.** Replace the string with an object
`{error_code, error_message, retryable}`, keeping the message. Codes, as
published in the document:

| Code | Retryable | Raised when |
|---|---|---|
| `malformed_request` | no | the body is not a usable execution message |
| `unsupported_capability` | no | capability not in `CAPABILITIES` (incl. `fix_recommendation`) |
| `entry_point_missing` | no | no entry point in `data` nor in `data.upstream` |
| `artifact_unavailable` | once | repository root or entry point unreadable |
| `trace_unavailable` | once | `trace_ref` does not resolve or cannot be read |
| `trace_ref_refused` | no | ref resolves outside `KIO2_TRACE_DIR` |
| `analysis_failed` | no | recording or slicing failed |
| `deadline_exceeded` | with a larger budget | recording hit `KIO2_TRACE_BUDGET` |
| `service_unavailable` | yes | starting up or shutting down |

The response schema (`schemas/kio2.response.schema.json`) and the tests that
validate real replies against it change with this, so do both together.

## 3. Authentication and authorisation (deployment profile R)

**Why.** `/execute` accepts a repository path and an entry point from anyone who
can reach it, and then runs them. That is remote code execution by design, and
"it is on the internal network" is not an access control.

**What to build.** Profile P (today, no auth) stays the default for the
prototype. Profile R needs: TLS on every endpoint except `/health`, a bearer
token or mTLS, and per-capability scopes so that a caller allowed to localise
cannot replay other workflows' recordings. Publish the profile in force in
`GET /tasks`.

## 4. Retention and masking of recorded values

**Why.** `crash_state`, the replay `state` and the diagnosis evidence carry real
values from the executed run, and traces under `KIO2_TRACE_DIR` are never
deleted. If the analysed program touches personal data, so do we.

**What to build.** A `KIO2_TRACE_TTL` (or an explicit delete endpoint) plus a
sweep, and an optional value-masking mode for the reply. Until then the
obligations sit with the deployment, which is what the document now states.

## 5. Smaller items

- **`/tasks` should publish `languages: ["python"]`.** The UC3 (C++/HLS) mismatch
  then surfaces at integration time instead of in a document footnote.
- **`status: "skipped"`.** A capability this deployment does not serve is closer
  to *skipped* than to *error*; KIO12 v0.5 added it for the same reason.
