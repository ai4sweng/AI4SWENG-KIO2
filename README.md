# KIO2 — AI-Assisted Fault Localizer

[![CI](https://github.com/ai4sweng/AI4SWENG-KIO2/actions/workflows/ci.yml/badge.svg)](https://github.com/ai4sweng/AI4SWENG-KIO2/actions/workflows/ci.yml)
[![Project Board](https://img.shields.io/badge/project-AI4SWENG_KIO2-blue)](https://github.com/orgs/ai4sweng/projects/31)

KIO2 turns a **failing execution** into a **ranked list of suspect statements**,
backed by runtime evidence rather than a guess. It is developed by **BitNet**
as part of the **AI4SWENG** European collaborative project, and this repository
holds its requirements, source code, and documentation.

<!--
  Add a short screenshot, GIF, or demo video of KIO2 in action here, for
  example the CLI locating the fault in the bundled dummy example, or the
  API response for a real repository. A rendered architecture diagram also
  fits well right below the Architecture section further down.

  <p align="center">
    <img src=".github/assets/demo.gif" alt="KIO2 locating a fault" width="720">
  </p>
-->

## Table of contents

- [KIO2 — AI-Assisted Fault Localizer](#kio2--ai-assisted-fault-localizer)
  - [Table of contents](#table-of-contents)
  - [What KIO2 does](#what-kio2-does)
  - [Repository layout](#repository-layout)
  - [Documentation map](#documentation-map)
  - [Getting started](#getting-started)
  - [Running with Docker](#running-with-docker)
  - [API contract](#api-contract)
  - [Contributing](#contributing)
    - [Creating a requirement](#creating-a-requirement)
    - [Creating a task](#creating-a-task)
  - [Project board and automation](#project-board-and-automation)

---

## What KIO2 does

Given a failing script, KIO2 records a trace of the run and localizes the fault. In addition to fault localisation, KIO2 provides **interactive replay** (forward/backward step navigation and point-in-time state inspection) and **trace alignment** to identify divergences between passing and failing executions.


**KIO2 stops at **localization**. It does not generate the fix. This is
**KIO7**'s job (see the [D2.6 boundary](docs/TECHNICAL_DOCUMENTATION.md#1-what-kio2-does)).** In changed requirements:



1. FR-KIO2-04 — Dynamic slicing -> **Post-mortem expression evaluator**
2. FR-KIO2-06 — Fine-tuned LLM for Bug Detection -> **AI-assisted mocking**
3. FR-KIO2-07 — Fix suggestion generation -> **Trace recorder**
4. FR-KIO2-08 — Thread-aware trace capture and replay simulation -> LLM Assisted Debugging??
   

The engine underneath is **FocusTracer**, an independent tool consumed here as
a library dependency, not vendored. KIO2 is the AI4SWENG service that wraps
FocusTracer behind the KIO contract, and is reachable both as a standalone API
and through the KIO1 dispatch protocol.

## Repository layout

| Path | Contents |
|---|---|
| `docs/` | All documentation: requirements, architecture, integration, and the trace format |
| `docs/requirements/` | One Markdown file per requirement (`FR-KIO2-01.md`, `NFR-KIO2-01.md`, ...) |
| `docs/architecture/` | Component breakdown (`architecture.yml`) |
| `docs/trace-schema/` | Reference documentation for the execution trace format |
| `schema/` | The trace format itself: one XSD per schema version, plus a legacy JSON Schema draft |
| `src/kio2/` | The service package: contract, runner, localizer, replayer, comparator, observability |
| `src/kio2/examples/` | A bundled failing example used when no target is supplied |
| `tests/` | The test suite, one file per requirement plus contract and protocol tests |
| `.github/workflows/` | CI (`ci.yml`): `ruff` + `pytest` on every push and PR |
| `Dockerfile` | Independent, headless API image |

## Documentation map

Start with the technical documentation for how KIO2 works end to end, or the
integration guide if you are wiring KIO2 into the platform.

| Document | Read this for |
|---|---|
| [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) | How KIO2 works: architecture, input/output, API, Docker, observability, requirement coverage |
| [`docs/INTEGRATION.md`](docs/INTEGRATION.md) | Wiring KIO2 into the AI4SWENG platform: both protocols, endpoints, payload examples, operational caveats |
| [`docs/trace-schema/`](docs/trace-schema/) | The trace file format FocusTracer records and KIO2 reads: structure, version history (v1 → v2.3), validation |
| [`docs/requirements/`](docs/requirements/) | Per-requirement specifications (FR, NFR, and task IDs), issue-template format |
| [`docs/architecture/architecture.yml`](docs/architecture/architecture.yml) | Component breakdown |
| [`src/kio2/README.md`](src/kio2/README.md) | Module-level design notes for the `kio2` package |

## Getting started

```bash
pip install -e ../../Trace/focustracer     # engine, needs >= 1.9 (or from Git — see requirements.txt)
pip install -e ".[dev]"                    # KIO2 service + pytest

# library demo:
python -c "from kio2 import localize; from kio2.dummy import dummy_input; print(localize(dummy_input()).message)"

# API service:
python -m kio2.main                        # POST /execute, GET /health/ on :8013

# lint + tests (same gates CI enforces):
ruff check .
pytest -q
```

> FocusTracer **≥ 1.9** is required: KIO2 imports `focustracer.core.{slicer,reverse,explain}`,
> the replay engine, and `align.TraceSet` / `AlignedPair.seek` (added in 1.9).
> An older install fails at import time.
> [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `ruff` and `pytest`
> on every push and PR, against Python 3.11 and 3.12.

## Running with Docker

```bash
docker build -t ai4sweng-kio2 .
docker run -p 8102:8102 ai4sweng-kio2   # the port KIO1's registry has for KIO2
```

## API contract

`POST /execute` serves three task types, chosen by `task_type` in the payload
(inferred from the payload shape when omitted, so older callers keep working):

| `task_type` | Payload | Returns | Requirement |
|---|---|---|---|
| `fault_localization` (default) | `target_script`, `working_directory`, `functions`, ... | `FaultLocalization`: ranked `suspect_lines`, `crash_state`, `confidence`, `handoff_context` | FR-KIO2-05 |
| `replay` | `trace_path` plus a start point (`seq` / `at_line` / `at_exception`) and `step_action` (`into` / `over` / `out`, `back`) | `ReplayView`: cursor, recorded state, timeline window, def-use | FR-KIO2-02 |
| `trace_alignment` | `trace_paths`: two traces (side-by-side) or three or more (a trace set) | `TraceComparison`: distance and divergences, or a matrix with reference and outlier | FR-KIO2-03 |

`GET /tasks` lists the live set; a bare `{}` payload uses the bundled dummy
example.

The same `POST /execute` also speaks the **KIO1 dispatch protocol**
(`workflow_id` / `step_id` / `capability` / `task` / `data` → `status` /
`output`), so the orchestrator can call KIO2 directly for `bug_localization`,
`diagnosis`, `replay`, and `trace_alignment`. Full details, including how the
two protocols are told apart on one endpoint, are in
[`docs/INTEGRATION.md`](docs/INTEGRATION.md#2-two-protocols-one-endpoint).

When dropped into the AI4SWENG platform, the service auto-upgrades to a full
KIO shell (NATS, capability announcements, HITL) with no code changes; see
[`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md#6-integrating-kio2-into-the-general-platform-repo).

## Contributing

### Creating a requirement

1. Go to **Issues → New Issue**.
2. Use the **Create New Requirement** template.
3. Fill in all fields (ID, description, priority, and so on).
4. The issue is linked automatically to the `AI4SWENG KIO2` project, under **Requirements**.

### Creating a task

1. Go to **Issues → New Issue**.
2. Use the **Create New Task** template.
3. Title must start with `[TASK]`.
4. The issue is routed automatically to the **Backlog** column of the project board.

## Project board and automation

Work items are tracked on a shared board:
[AI4SWENG KIO2 Project Board](https://github.com/orgs/ai4sweng/projects/31)
(columns: `Requirements`, `Backlog`, `In Progress`, `Done`).

Issues are routed to the board by title prefix or label:

| Title prefix / label | Routed column |
|---|---|
| `[REQ]`, `requirement` | `Requirements` |
| `[TASK]` | `Backlog` |

This routing is configured in **GitHub Projects itself** (Project → Settings →
Workflows), not by a GitHub Action: organization-level ProjectsV2 needs a
token with `project` scope, which the default `GITHUB_TOKEN` does not have and
`permissions:` cannot grant. The only GitHub Action in this repository is
[`ci.yml`](.github/workflows/ci.yml): `ruff` and `pytest` on every push and PR.

---

Owned and maintained by **BitNet**, as part of the **AI4SWENG** collaborative project.
