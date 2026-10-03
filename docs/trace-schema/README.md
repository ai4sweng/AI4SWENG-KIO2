# Trace Schema

The Trace Schema defines the XML format that FocusTracer writes when it records
a Python program's execution, and that KIO2 reads back when it slices, replays,
or aligns that recording. Every trace file KIO2 produces or consumes is an
instance of this schema.

This directory documents the format on its own terms, independently of the
KIO2 service that consumes it, so it can be read, validated, and produced by
any tool without going through KIO2's Python code.

## Contents

| Document | Purpose |
|---|---|
| [Overview](overview.md) | What the schema is for, who produces and reads it, and where it sits in the KIO2 pipeline |
| [Format reference](format.md) | The structure of a trace file: root element, metadata, event hierarchy, and the slicing extension |
| [Version history](versions.md) | What changed between v1 and v2.3, and which version KIO2 requires |
| [Working with the schema](usage.md) | How a trace is generated, how to validate one, and how to point KIO2 at a schema version |
| [`/schema/`](../../schema/) | The schema definitions themselves: one XSD per version, plus a legacy JSON Schema draft |

## In one sentence

A trace file is a `<trace>` document holding `<metadata>` about the run and an
`<events>` tree that records every executed line, function call, and variable
change, in the order and nesting they happened in.

## Current version

KIO2 targets **schema v2.3**, the version that adds the `<reads>` and
`<slice>` elements dynamic slicing depends on. See
[Version history](versions.md) for the full changelog and
[Working with the schema](usage.md) for how KIO2 selects a version.
