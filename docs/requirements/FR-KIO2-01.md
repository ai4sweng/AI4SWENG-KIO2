# FR-KIO2-01 — Source code language support (One language for PoC)

> Mirrors the repository's `📄 Create New Requirement` issue template.

| Field | Value |
|---|---|
| **Requirement ID** | FR-KIO2-01 |
| **Title** | Source code language support (One language for PoC) |
| **Owner (Partner)** | BITNET |
| **Contributors (Partner)** | HESSO |
| **Priority** | High |

## Objective (Purpose)

Provide foundational support for the selected PoC language, enabling parsing,
execution, and **trace generation**. All downstream KIO2 requirements build on
this choice.

## Description (Scope)

Select **one** primary language for the PoC (**Python**) and provide the minimal
tooling to build, run, and lint it locally and in CI, with a consistent code
style.

## Constraints / Assumptions

- One primary language for the PoC: **Python**.
- **C is out of scope** for this PoC. The objective mentions "Python and/or C",
  but the constraint selects a single language; our engine (FocusTracer) is
  Python-only. C tracing, if ever required, is separate future work.
- Tooling for build, run, and lint is provided.

## Acceptance Criteria

The PoC environment successfully interprets Python and **produces a valid trace
file upon execution** (schema-validated). ✔ Covered by
`tests/test_fr_kio2_01_language_support.py` (runs a Python target → asserts the
produced trace passes XSD validation).

## How KIO2 satisfies it

- **Language = Python.** The engine (FocusTracer) instruments Python at runtime.
- **Zero-touch instrumentation.** FocusTracer activates via scope-gated runtime
  monkey-patching — it does **not** modify the target's source or bytecode. This
  directly satisfies the invariant "instrumentation must not alter program
  semantics or output" (no compilation step; Python is interpreted).
- **Valid trace output.** `runner.run_trace` drives `focustracer run`, which
  writes a schema-`2.3` XML trace and validates it against the bundled XSD.
- **Tooling.** `pyproject.toml` (build/deps), CLI + `python -m kio2.main` (run),
  `pytest` (test), and a minimal `ruff` config (lint/style).

## Dependency (Relationship)

- **Blocks:** FR-KIO2-02 … FR-KIO2-08 (all depend on this language/engine choice).
- **Related to:** NFR-KIO2-03 (Modularity) — packaging standards.

## Pre-Condition(s)

1. Development environment configured (Python ≥ 3.10).
2. Trace engine (FocusTracer) installed and accessible.
3. Toolchain installed (`pip`, `pytest`).

## Input

Python source files + build configuration (`pyproject.toml`).

## Invariants

- Trace instrumentation must not alter program semantics or output
  (guaranteed by zero-touch scope-gated patching).
- Trace generation is deterministic/reproducible for the same input and config.

## Behaviour and Sequences

1. Target Python program is provided (repo + entrypoint).
2. FocusTracer hooks the target functions at runtime (no source change).
3. Execution is traced → schema-2.3 XML trace, XSD-validated.

## Output

An executable Python target that runs with trace capture enabled, producing a
valid, reproducible trace file.

## Post–Condition(s)

The PoC runtime executes correctly with trace capture enabled and produces a
schema-valid trace ready for the downstream KIO2 stages (slicing, replay,
localization).

## Status

✅ **Satisfied** by the existing stack (Python + FocusTracer). Deliverables added
for this requirement: this spec, the acceptance test, and the lint config.
