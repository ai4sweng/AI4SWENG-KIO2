# Version history

The schema version is carried in the trace file itself, as the
`schema_version` attribute on the root `<trace>` element (and, redundantly,
inside `<metadata>` from v2.0 onward). Each version after v1 was additive: a
file written by an older version stays valid input to a newer reader, because
every field a version adds is optional.

| Version | File | Status |
|---|---|---|
| 1.0 | [`schema/trace_schema_v1.xsd`](../../schema/trace_schema_v1.xsd) | superseded |
| 2.0 | [`schema/trace_schema_v2.xsd`](../../schema/trace_schema_v2.xsd) | superseded |
| 2.1 | [`schema/trace_schema_v2.1.xsd`](../../schema/trace_schema_v2.1.xsd) | superseded |
| 2.2 | [`schema/trace_schema_v2.2.xsd`](../../schema/trace_schema_v2.2.xsd) | superseded |
| 2.3 | [`schema/trace_schema_v2.3.xsd`](../../schema/trace_schema_v2.3.xsd) | **current** — required by KIO2's slicing |

## v1.0 — flat event log

The original format. `<events>` was a flat, unordered list of `<event>`
elements; there was no `<scope>`, `<loop>`, or `<thread>` grouping, no
`schema_version` attribute, and every event repeated a full `<locals>`
snapshot. Readable for short traces, but a full-snapshot flat list does not
scale to real programs.

## v2.0 — hierarchical restructuring

The structural rewrite that every later version builds on:

- Added `<loop>` for loop compaction (one entry per loop, not per iteration
  duplicated as flat lines).
- Added `<scope>` for hierarchical function grouping, so a trace mirrors the
  program's own call tree.
- Added `<thread>` for thread-based event grouping.
- Added the `schema_version` attribute on the root `<trace>` element.
- Changed `<locals>` to no longer appear on every line event; line-level state
  is a `<delta>` against the previous event instead.

## v2.1 — thread nesting completed

Refined the v2.0 hierarchy: `<iteration>` (inside `<loop>`) can now contain
nested `<scope>` and `<loop>` elements directly, not only flat `<event>`
elements, so a loop body that calls functions or contains nested loops is
represented correctly rather than flattened.

## v2.2 — timing and diagnostics

- Added `start_time`, `end_time`, and `duration` attributes on `<scope>`, for
  per-call timing without a separate profiler.
- Added `start_time` and `end_time` attributes on `<iteration>`, for
  per-iteration timing.
- Added `<traceback>` inside `<exception>`, carrying the full stack trace text
  for post-mortem debugging.
- Added `<targets>` and `<source_files>` inside `<metadata>`, recording which
  functions or files were instrumented and which files actually produced
  events.

All v2.2 additions are optional, so v2.1 files remain valid under the v2.2
schema.

## v2.3 — dynamic slicing support (current)

- Added `<reads>` on `<event>`: the set of variables a line *read*, as
  distinct from `<delta>`, which records what it *changed*. This is the
  use-set that backward dynamic slicing depends on, and it is written only in
  `detailed` recording mode.
- Added `<slice>` (with `<node>` children) as an optional child of the root
  `<trace>` element: the backward dynamic slice computed from a crash or a
  specific value, tagged per node as `criterion`, `data`, or `control`
  dependency.

KIO2 requires **v2.3** because its fault localizer (`localizer.py`) depends on
both `<reads>` and `<slice>` being present; see
[Working with the schema](usage.md) for how KIO2 requests this version when it
records a trace.

## A note on `trace_schema.json`

[`schema/trace_schema.json`](../../schema/trace_schema.json) is an early JSON Schema
draft written before the v2 hierarchical restructuring. It describes trace
events as a flat array under different field names (`seq`, `etype`, `frame`)
and does not reflect the current `<scope>`/`<loop>`/`<thread>` structure. It
is kept for historical reference only; the XSD files are the authoritative
format.
