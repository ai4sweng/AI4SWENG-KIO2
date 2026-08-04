# FR-KIO2-02 — Trace Capture & Replay to generate reversible trace data

> Mirrors the repository's `📄 Create New Requirement` issue template.

| Field | Value |
|---|---|
| **Requirement ID** | FR-KIO2-02 |
| **Title** | Trace Capture & Replay to generate reversible trace data |
| **Owner (Partner)** | BITNET |
| **Contributors (Partner)** | HESSO |
| **Priority** | High |

## Objective (Purpose)

A debugger-like capability for interactively manipulating execution traces:
forward/backward navigation, state-snapshot inspection, def-use chain
visualization, and post-mortem interactive debugging sessions.

## Description (Scope)

A **backend engine** that consumes a trace file and exposes an **API** for
traversing states (Step Over / Into / Out / Back) and reconstructing memory,
which a UI or CLI can drive.

## Constraints / Assumptions

- Support the **Debug Adapter Protocol (DAP)** *where possible*.
  → **Not implemented yet** (out of proportion for the PoC). The engine exposes
  the equivalent operations (step into/over/out/back, state, source, def-use);
  a thin DAP adapter over this API is possible future work.

## Acceptance Criteria

Forward/backward navigation behaves like a standard debugger, and state
reconstruction matches the recorded snapshots exactly.
✔ Covered by FocusTracer tests: `tests/test_replay.py` (step into/over/out,
depth, backward) and `tests/test_reverse.py` (exact state reconstruction).

## How KIO2 satisfies it (engine = FocusTracer)

This is an **engine-level** requirement; the implementation lives in the
**FocusTracer** dependency (KIO2 consumes it). Coverage:

| Behaviour (from the spec) | FocusTracer | Status |
|---|---|---|
| Read-only source viewer, syntax highlighting | GUI (CodeMirror + Python) | ✅ |
| Jump-to-definition (language server) | basic viewer only | 🟡 partial (no LSP) |
| Step backward | `reverse` / `replay` `step_back` | ✅ |
| **Step into / over / out** | `ReplaySession.step_into/over/out` (+`back`) | ✅ **(added for this FR)** |
| State viewer (recorded snapshots) | `reverse`/`replay` `state()`; GUI state view | ✅ |
| Program slice visualizer (def-use) | `slice`; GUI Slice tab | ✅ |
| API for a UI or CLI to drive | `ReplaySession` API + CLI `replay` + GUI endpoints | ✅ |
| DAP support ("where possible") | — | ❌ not yet (see constraint) |

Step into/over/out are computed over the recorded timeline using each moment's
call-stack **depth**: *into* = next line (enters calls); *over* = next line in
the current frame, skipping called frames; *out* = leave the current frame into
its caller. Each also works **backward** (reverse execution).

## Dependency (Relationship)

- **Depends on:** FR-KIO2-07 (trace recorder), FR-KIO2-01 (language/engine).
- **Feeds:** FR-KIO2-04 (post-mortem inspection), FR-KIO2-05 (localization uses
  the same slice/replay primitives).

## Pre-Condition(s)

1. Trace capturing is available (FR-KIO2-07).
2. Python source files corresponding to the trace are available.

## Input

An execution trace + the corresponding source files.

## Invariants

The state viewer presents exactly the data that was recorded (no re-execution;
values are the observable recorded state).

## Behaviour and Sequences

1. Load a saved trace (read-only).
2. Navigate: step backward / into / over / out; jump to event/line/exception.
3. Inspect the reconstructed state at the cursor.
4. Visualize the backward dynamic slice (def-use) for a value of interest.

## Output

An API (`ReplaySession`) that a UI or CLI drives — CLI `focustracer replay`
(`--into/--over/--out/--back/--step/--def`), and GUI Replay/Slice/Reverse tabs.

## Post–Condition(s)

Forward navigation within a trace matches the navigation behaviour of a regular
debugger over the original program; reconstructed state matches the recording.

## Status

✅ **Satisfied** (engine). Newly added for this FR: debugger-grade Step
Into/Over/Out (+ backward) in FocusTracer `ReplaySession` and CLI `replay`.
Open/partial: DAP adapter and full LSP jump-to-definition (both low priority).
