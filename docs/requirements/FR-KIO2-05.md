# FR-KIO2-05 — AI Fault Localisation

> Mirrors the repository's `📄 Create New Requirement` issue template so this
> document and its GitHub issue stay in lock-step.

| Field | Value |
|---|---|
| **Requirement ID** | FR-KIO2-05 |
| **Title** | AI Fault Localisation from replayed traces and slice context |
| **Owner (Partner)** | BitNet |
| **Contributors** | — |
| **Priority** | High |

## Objective (Purpose)

Turn a failing execution into a **ranked list of suspect statements** with
runtime evidence, so a developer (or the downstream fix agent, KIO7) knows
*where* the bug is before deciding *how* to fix it. Localisation is grounded in
dynamic evidence (an execution trace + a backward dynamic slice), not in
LLM guesswork.

## Description (Scope)

KIO2 records the failing run, computes a backward dynamic slice from the crash
(or a given criterion), and scores the statements on that slice by their causal
role. It returns the ranked suspects plus the crash state and a value-annotated
slice context. **Scope boundary (D2.6):** KIO2 stops at localisation; fix
generation belongs to **KIO7**. The slice context is packaged as `handoff_context`
for KIO7.

## Constraints / Assumptions

- Python source (PoC language, FR-KIO2-01).
- The failing execution must be reproducible under tracing (`detailed`,
  schema ≥ 2.3) — this is what the FocusTracer engine records (FR-KIO2-07).
- Recovers the *observable* (string) state, not live Python objects; no re-run
  beyond the initial capture.

## Acceptance Criteria

- For a crashing program, suspect #1 is the crash statement (criterion), scored
  highest.
- Output includes ranked suspects (with file/function/line/source), the crash
  state, a confidence value, and `handoff_context` for KIO7.
- Low confidence raises a HITL review (`REVIEW_REQUIRED`) instead of silently
  proceeding.
- Dynamic-slicing isolation rate meets the WP3 target (≥ 0.85) on the benchmark
  set (reported via `kio.slicing.success_rate`).

## Dependency (Relationship)

- **Prev:** FR-KIO2-07 (Trace recorder), FR-KIO2-04 (slicing/post-mortem),
  FR-KIO2-02 (replay/reverse) — all provided by the FocusTracer engine.
- **Next:** KIO7 (fix generation) consumes `handoff_context`.
- **Upstream input:** the failing test/execution normally comes from KIO11
  (test automation) — dummy until that contract is agreed jointly with KIO11.

## Pre-Condition(s)

1. A target script / repo and a failing entrypoint or exception are available.
2. FocusTracer is installed (engine dependency).

## Input

`Kio2Input`: `target_script`, `working_directory`, `functions` (optional trace
targets), `criterion` (optional `[FILE:]LINE[:VAR]`; default = crash),
`failing_test` (context from KIO11, optional).

## Invariants

- Read-only over the trace; localisation never mutates the trace or the target.
- Deterministic for an identical trace.
- KIO2 never emits a fix — only localisation + hand-off context.

## Behaviour and Sequences

1. **Record** the failing run under FocusTracer → schema-2.3 trace (`runner.py`).
2. **Slice** backward from the crash/criterion (data + control deps).
3. **Rank** the slice statements (criterion 1.0 > control 0.75 > data 0.5),
   de-duplicated by `file:line`.
4. **Reconstruct** the crash state (reverse execution, best-effort).
5. **Package** the value-annotated slice as `handoff_context` for KIO7.
6. **Gate**: compute confidence; if low, return `REVIEW_REQUIRED` (HITL).

Pipeline position (D2.6 UC-UC1-03): KIO11 confirms failure → **KIO2 localises**
→ KIO7 fixes → HITL approves.

## Output

`FaultLocalization`: `status`, `criterion`, `suspect_lines[]` (rank, score,
dependency, file, function, line, source), `crash_state`, `confidence`,
`handoff_context`, `trace_path`, `message`.

## Post–Condition(s)

- Each suspect statement is mapped to its causal role and runtime evidence.
- A localisation artifact is produced and (in-platform) stored for traceability
  and handed to KIO7.

## Implementation

- Code: `src/kio2/localizer.py` (core), `src/kio2/runner.py` (capture),
  `src/kio2/contract.py` (interface), `src/kio2/service.py` (API handler).
- Engine: FocusTracer (`slicer`, `reverse`, `replay`, `explain`) — dependency.
- Tests: `tests/test_kio2.py`.
