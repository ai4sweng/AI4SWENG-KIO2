# KIO2: Bug Locate & Fix

[![CI](https://github.com/ai4sweng/AI4SWENG-KIO2/actions/workflows/ci.yml/badge.svg)](https://github.com/ai4sweng/AI4SWENG-KIO2/actions/workflows/ci.yml)
[![Project Board](https://img.shields.io/badge/project-AI4SWENG_KIO2-blue)](https://github.com/orgs/ai4sweng/projects/31)

KIO2 finds where a Python program failed. It runs the program once, records
every executed line, and works back from the error to the lines that caused it,
with the values they held at the time. Everything it reports comes from a real
run, not from a guess.

KIO2 is developed by **BitNet** in the **AI4SWENG** European project. It runs as
an HTTP service that the orchestrator (KIO1) calls, and it is built on
[FocusTracer](https://github.com/BitnetTR/focustracer), the tracing engine.

## Quick start

Requires Python 3.10 or later. One command installs KIO2 and FocusTracer:

```bash
pip install "ai4sweng-kio2 @ git+https://github.com/ai4sweng/AI4SWENG-KIO2.git"
```

Start the service:

```bash
python -m kio2.main
```

Then open **http://127.0.0.1:8102/docs**. Under **POST /jobs** press *Try it
out*, keep the example *bug_localization: failing example* and press *Execute*.
Copy the `job_id` into **GET /jobs/{job_id}** to read the result: the fault is
at line 15 of a bundled example that divides by zero.

## What it does

| Capability | What it does | Needs |
|---|---|---|
| `bug_localization` | Record the program and report the lines behind the error. | the code and the script to run |
| `diagnosis` | The same, written as a root cause, plus the annotated slice a fix step can use. | the code and the script to run |
| `replay` | Walk through a recording line by line, forwards or backwards, and read the variables. | a recording |
| `trace_alignment` | Compare two or more recordings of the same program and show where they differ. | two or more recordings |

KIO2 stops at finding the fault. Writing the fix is KIO7's job. It supports
Python programs, and it only localises failures that raise an error: a program
that ends with a wrong result is reported as `clean`.

## Working on the code

```bash
git clone https://github.com/ai4sweng/AI4SWENG-KIO2.git
cd AI4SWENG-KIO2
pip install -e ".[dev]"
pytest -q            # the same checks CI runs, with: ruff check .
```

`pip install -e .` installs FocusTracer from GitHub. If you also change the
engine, install your local copy **afterwards**, so it is not replaced:

```bash
pip install -e ../focustracer
```

Settings such as where traces are written are read from a `.env` file; copy
[`.env.example`](.env.example) to start. The port is `KIO_PORT` (default 8102).

## Running with Docker

```bash
docker compose up --build
```

The service listens on port 8102. KIO2 can only run code it can see, so put the
code to analyse under `./workspace` and refer to it as `/workspace/...` in a
request.

## How KIO1 calls KIO2

| Endpoint | Purpose |
|---|---|
| `POST /jobs`, `GET /jobs/{job_id}` | The job protocol KIO1 uses: submit, then poll for the result. |
| `POST /execute` | The same analysis in one synchronous call, for scripts and tests. |
| `GET /traces/{token}` | A recorded trace, as XML. |
| `GET /health`, `GET /tasks`, `GET /schema` | Health, capabilities and the published JSON schemas. |
| `GET /docs` | Interactive API documentation with ready-to-run examples. |

[`docs/index.html`](docs/index.html) explains the input and output fields and
links to step-by-step diagrams of each flow.
[`docs/INTEGRATION.md`](docs/INTEGRATION.md) has the full protocol.

## Repository layout

| Path | Contents |
|---|---|
| `src/kio2/` | The service. See [`src/kio2/README.md`](src/kio2/README.md) for the modules. |
| `src/kio2/examples/` | A failing program and its corrected version, used by the examples. |
| `tests/` | The pytest suite. |
| `tests/scenarios/` | Fifteen buggy programs to try KIO2 by hand, and the D3.3 benchmarks. |
| `docs/` | Guide (`index.html`), diagrams (`web/`), integration and technical documentation, requirements. |
| `schema/` | The trace file format, one XSD per version. |
| `workspace/` | Where Docker looks for code to analyse. |

## Documentation

| Document | Read it for |
|---|---|
| [`docs/index.html`](docs/index.html) | A short guide with a form to try KIO2 from the browser. |
| [`docs/INTEGRATION.md`](docs/INTEGRATION.md) | Connecting KIO2 to the AI4SWENG platform. |
| [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) | How KIO2 works inside, observability, requirement coverage. |
| [`docs/trace-schema/`](docs/trace-schema/) | The trace file format and its versions. |
| [`docs/requirements/`](docs/requirements/) | One file per requirement (FR-KIO2-xx, NFR-KIO2-xx). |

## Contributing

Requirements and tasks are GitHub issues, tracked on the
[project board](https://github.com/orgs/ai4sweng/projects/31). Open an issue with
the **Create New Requirement** template (title `[REQ] ...`) or the **Create New
Task** template (title `[TASK] ...`); the board sorts them into *Requirements*
and *Backlog*. CI runs `ruff` and `pytest` on every push and pull request.

---

Owned and maintained by **BitNet**, as part of the **AI4SWENG** collaborative project.
