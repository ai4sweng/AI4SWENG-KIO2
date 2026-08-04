# FR-KIO2-03 — Trace alignment (AI-assisted replay simulators)

> Mirrors the repository's `📄 Create New Requirement` issue template.

| Field | Value |
|---|---|
| **Requirement ID** | FR-KIO2-03 |
| **Title** | AI-assisted replay simulators that reconstruct previous states from logged diffs |
| **Owner (Partner)** | BITNET |
| **Contributors (Partner)** | HESSO |
| **Priority** | High |

## Objective (Purpose)

Manipulate **multiple** execution traces in a single interactive session to
compare across runs; align traces with heuristics inspired by **bioinformatics
sequence alignment**; lay the foundation for curating sets of traces.

## Description (Scope)

The requirement's description also lists a heavier ML pipeline (dataset curation
& schema, feature engineering & temporal windowing, model selection/training,
model registry & MLOps, privacy/compliance).
→ **Scope decision:** the concrete Behaviour/Output/Invariant below (alignment +
distance + multi-trace navigation) are implemented now. The ML-pipeline framing
is **deferred / cross-partner future work** (same treatment as the FR-KIO2-05
anomaly-ML technique) — it is a WP-level effort, not a single-service deliverable.

## Acceptance Criteria

_(not specified in the issue)_ — verified against the invariant and outputs:
identical traces have distance 0; different runs yield a positive distance and a
gap-annotated alignment. ✔ Covered by `tests/test_align.py`.

## Dependency (Relationship)

- **Depends on:** FR-KIO2-02 (replay engine) — provides the per-trace timeline.

## Pre-Condition(s)

The replay engine is implemented and available (FR-KIO2-02). ✅

## Input

A set of execution traces of a **single program** run with different inputs /
configurations, plus the corresponding source files.

## Invariants

**The distance between identical traces is 0.** ✔ (enforced by the alignment
cost: equal statement sequences ⇒ cost 0).

## Behaviour and Sequences

1. Extend the replay engine to navigate multiple traces simultaneously
   (`AlignedPair`: a cursor on trace A maps to the aligned moment in trace B).
2. Best-effort alignment of the executed-statement sequences despite divergences
   (global sequence alignment, à la Needleman-Wunsch), so state can be inferred
   across traces at aligned points.

## Output

- **A distance measure** between two traces (`distance`, `normalized_distance`)
  indicating how (dis)similar they are.
- **An alignment encoding** — `pairs` of `(a_index | None, b_index | None)`:
  matched positions and gaps (divergences).

## How KIO2 satisfies it (engine = FocusTracer)

Engine-level; implemented in **FocusTracer** (`core/align.py`), consumed by KIO2.

| Item | Implementation |
|---|---|
| Sequence alignment (bioinformatics-inspired) | `align_sequences` (Needleman-Wunsch), `align_traces` |
| Distance measure (identical ⇒ 0) | `Alignment.distance` / `trace_distance` |
| Alignment encoding | `Alignment.pairs` (matches + gaps) |
| Navigate multiple traces at once | `AlignedPair.aligned_state()` |
| CLI | `focustracer align A.xml B.xml [--show-alignment] [--json]` |

Example: same program with inputs `[1,2,3]` vs `[1,2,3,4,5]` → distance 2, 5
matched statements, 2 gaps (the extra loop iterations). `A vs A` → distance 0.

## Post–Condition(s)

_(not specified)_ — a reusable distance + alignment is produced for a pair of
traces and can seed trace-set curation.

## Status

🟡 **Core satisfied** (alignment + distance + multi-trace navigation, FocusTracer
v1.8.0). **Deferred:** the ML pipeline in the Description (dataset curation,
model training, MLOps, privacy) — future / cross-partner.
