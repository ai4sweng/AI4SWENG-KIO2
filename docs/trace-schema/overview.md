# Overview

## What problem this solves

To locate a bug, replay a crash, or compare two runs of the same program, KIO2
needs a record of what actually happened while the program executed: which
lines ran, in what order, with which variable values, and how one function
call was nested inside another. That record is a **trace**, and the Trace
Schema is the file format it is written in.

Without a fixed format, every part of the pipeline that reads a trace
(the replay engine, the aligner, the localizer) would have to agree on an
ad hoc structure by convention. The schema removes that ambiguity: it is the
single contract between the component that records a trace and every
component that later reads one.

## Where it fits in the pipeline

```
 target program ──► FocusTracer recorder ──► trace file (XML, this schema)
                                                    │
                    ┌───────────────────────────────┼───────────────────────────────┐
                    ▼                                ▼                               ▼
              KIO2 localizer                  KIO2 replayer                  KIO2 comparator
        (slice + rank suspects)         (step through the run)         (align two or more runs)
```

FocusTracer is the engine that instruments a running Python program and writes
the trace. KIO2 is the AI4SWENG service that consumes FocusTracer as a library:
`runner.py` starts a traced run and produces the file, and `localizer.py`,
`replayer.py`, and `comparator.py` read it back. None of those three components
re-run the program: they work entirely off the recorded file, which is what
makes post-mortem debugging and multi-run comparison possible without
re-executing anything.

## What a trace captures

A trace is built around **events**: one call, one executed line, one return,
or one raised exception. Events are grouped into a hierarchy that mirrors the
program's own call structure, so a trace reads like a nested log of function
calls rather than a flat list, and loops are compacted so that a thousand
iterations do not produce a thousand duplicate entries.

Each event carries enough state to answer "what changed here": which
variables were added, changed, or removed since the previous event, not a
full snapshot repeated on every line. Full snapshots are kept only where they
matter, at the moment a function is called or returns.

From version 2.3 onward, a trace can also carry a **slice**: the subset of
events that a backward dynamic slice identified as relevant to a specific
crash or value, which is what KIO2's fault localizer ranks and hands off to
the fix-generation stage.

## Who reads and writes it

- **Producer:** FocusTracer's trace recorder, invoked through KIO2's
  `runner.py` (see FR-KIO2-07 in [`docs/requirements/`](../requirements/)).
- **Consumers:** KIO2's `localizer.py` (fault localization, FR-KIO2-05),
  `replayer.py` (post-mortem navigation, FR-KIO2-02), and `comparator.py`
  (trace alignment, FR-KIO2-03). All three are read-only over the file; they
  never re-run the traced program.
- **Format details:** see [Format reference](format.md) for the element
  structure, or [Version history](versions.md) for what each schema version
  added.
