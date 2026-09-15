# Format reference

This describes the current schema, v2.3
([`schema/trace_schema_v2.3.xsd`](../../schema/trace_schema_v2.3.xsd)). For what
changed in earlier versions, see [Version history](versions.md).

## Document structure

Every trace file has the same top-level shape:

```
<trace schema_version="2.3">
  <metadata>...</metadata>
  <events>...</events>
  <slice>...</slice>          <!-- optional -->
</trace>
```

### `<metadata>`

Describes the run that produced the trace, not the run itself:

| Element | Meaning |
|---|---|
| `python_version` | interpreter version, for example `3.11.0` |
| `platform` | operating system, for example `win32` or `linux` |
| `start_time` / `end_time` | ISO 8601 timestamps bounding the recording |
| `statistics` | counters: `total_events`, `total_duration`, and optionally `call_count`, `line_count`, `return_count`, `exception_count` |
| `targets` | which functions or files were instrumented (added in v2.2) |
| `source_files` | which source files produced at least one event (added in v2.2) |

### `<events>`

The container for everything that happened during the run. It holds a mix of
four element kinds, in execution order:

| Element | Represents |
|---|---|
| `<event>` | a single call, line, return, or exception |
| `<scope>` | one function call, wrapping everything that happened inside it |
| `<loop>` | one `for` or `while` loop, wrapping its iterations |
| `<thread>` | events belonging to one thread, when threading is used |

`<scope>`, `<loop>`, and `<thread>` all nest: a `<scope>` can contain further
`<scope>` and `<loop>` elements, mirroring nested calls and loops in the
source program. This is what makes a trace read like the program's own call
tree instead of a flat instruction log.

### `<scope>` — one function call

```xml
<scope function="average_price" file="cart.py" call_line="9" depth="1"
       start_time="1718000000.123" end_time="1718000000.130" duration="0.007">
  <arguments>
    <arg name="items" type="list">[{...}, {...}]</arg>
  </arguments>
  <event id="12" type="line" timestamp="1718000000.124">
    <line>11</line>
    <source>prices = [it['price'] for it in items if it['in_stock']]</source>
  </event>
  <return_value name="return" type="float">4.5</return_value>
</scope>
```

`start_time`, `end_time`, and `duration` (added in v2.2) make per-call timing
available without a separate profiling pass. A scope ends with either a
`return_value` or an `exception`, never both.

### `<loop>` — compacted iterations

```xml
<loop line="10" source="for it in items:" iterations="3" type="for">
  <iteration index="0" start_time="..." end_time="...">
    <event id="8" type="line"><line>11</line><source>...</source></event>
  </iteration>
  <iteration index="1">...</iteration>
  <iteration index="2">...</iteration>
</loop>
```

Loops are recorded per iteration rather than as a flat repetition of line
events, which keeps a trace over a long-running loop readable. When
`max_iterations` truncates recording, the `truncated_iterations` attribute
reports how many iterations were skipped, and a `<summary>` element carries
the overall variable-change summary for the whole loop instead.

### `<event>` — the atomic unit

```xml
<event id="12" type="line" timestamp="1718000000.124" depth="2">
  <line>11</line>
  <source>prices = [it['price'] for it in items if it['in_stock']]</source>
  <delta>
    <change name="prices" action="added" type="list">
      <new>[19.99, 5.5]</new>
    </change>
  </delta>
  <reads>
    <read name="items" type="list">[{...}, {...}]</read>
  </reads>
</event>
```

`type` is one of `call`, `line`, `return`, or `exception`. `file` and
`function` are only written directly on an event when it is not already
nested inside a `<scope>` or `<thread>` that names them; a reader falls back
to the enclosing element in that case.

State is recorded two ways, depending on where the event sits:

- **`<delta>`** — on `line` events, only the variables that changed since the
  previous event, tagged `added`, `changed`, or `removed`. This is the
  default: a full snapshot on every line would make traces of any real size
  unreadable.
- **`<locals>` / `<arguments>` / `<return_value>`** — full snapshots, written
  only at the boundaries that matter: a function's arguments at `call`, its
  full locals and return value at `return`.

**`<reads>`** (added in v2.3) lists the variables a line *used*, as opposed to
`<delta>`, which lists what it *changed*. This use-set is what backward
dynamic slicing walks to find which earlier statements a given line depends
on; it is written only in `detailed` recording mode.

### `<slice>` — the dynamic slice (v2.3+)

```xml
<slice criterion="exception@buggy_order_total.py:15" criterion_event="42">
  <node line="15" event_id="42" function="average_price" dependency="criterion"
        source="return total / len(prices)"/>
  <node line="11" event_id="12" function="average_price" dependency="data"
        source="prices = [it['price'] for it in items if it['in_stock']]"/>
</slice>
```

A `<slice>` is the output of a backward dynamic slice computed from a
`criterion` (a crash or a specific `file:line[:var]`). Each `<node>` is one
statement the slice includes, tagged with why it is there:

| `dependency` | Meaning |
|---|---|
| `criterion` | the statement that triggered the slice (the crash itself) |
| `data` | reached through a data dependency (it produced a value the criterion used) |
| `control` | reached through a control dependency (it decided whether the criterion ran at all) |

This is the element KIO2's fault localizer ranks to produce `suspect_lines`.

## Type reference

| Type | Used for |
|---|---|
| `ValueType` | any named, typed value: an argument, a local, a return value, a delta's old/new, a read |
| `DeltaType` / `DeltaChangeType` | the `added` / `changed` / `removed` variable changes on a line |
| `ReadsType` | the set of variables a line read (v2.3) |
| `ExceptionType` | exception `type`, `value`, and optionally a full `traceback` (v2.2) |
| `SliceType` / `SliceNodeType` | the backward dynamic slice and its nodes (v2.3) |

See [`schema/trace_schema_v2.3.xsd`](../../schema/trace_schema_v2.3.xsd) for the
authoritative, complete definition, including which fields are required
versus optional.
