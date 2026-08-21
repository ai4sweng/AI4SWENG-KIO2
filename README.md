# AI4SWENG-KIO2

Welcome to the repository for **KIO2 (Key Innovation 2)**, owned and developed by **BitNet** as part of the AI4SWENG European collaborative project.

This repository centralizes all assets related to the development, documentation, requirements, and demonstration of KIO2.

---

## 📌 Purpose of This Repository

- Collect, track, and version **functional and non-functional requirements** for KIO2
- Develop and maintain **source code and demo artifacts**
- Automate **project board workflows** (issue routing, status updates)
- Provide transparency and enable collaboration across partners

---

## 🗂️ Folder Structure

| Folder                  | Description                                                                 |
|-------------------------|-----------------------------------------------------------------------------|
| `docs/`                 | All documentation related to KIO2: requirements, architecture, planning    |
| ├── `requirements/`     | Markdown files for each requirement (e.g. `FR-KIO2-01.md`)                  |
| └── `architecture/`     | Diagrams, high-level design, and component breakdown                        |
| `src/`                  | Source code, scripts, or prototype implementations                          |
| `.github/workflows/`    | GitHub Actions — `ci.yml` (ruff + pytest gates) and issue-to-project routing |

---

## ✅ How to Contribute

### 🔹 1. Creating a Requirement
- Go to **Issues > New Issue**
- Use the `📄 Create New Requirement` template
- Fill in all fields (ID, description, priority, etc.)
- The issue will be automatically linked to the `AI4SWENG KIO2` project under **Requirements**

### 🔹 2. Creating a Task
- Go to **Issues > New Issue**
- Use the `🛠️ Create New Task` template
- Title must start with `[TASK]`
- It will automatically be routed to the **Backlog** column of the project board

---

## Project Board (GitHub Projects v2)

We manage all work items through a shared board:
👉 [AI4SWENG KIO2 Project Board](https://github.com/orgs/ai4sweng/projects/31)

Columns include:
- `Requirements`
- `Backlog`
- `In Progress`
- `Done`

---

## 🔁 Automation

All issues are auto-routed based on title or label:
| Title Prefix / Label   | Routed Column   |
|------------------------|-----------------|
| `[REQ]`, `requirement` | `Requirements`  |
| `[TASK]`               | `Backlog`       |

Automation logic is located in [`.github/workflows/smart-issue-to-project.yml`](.github/workflows/smart-issue-to-project.yml).

---

## 🧩 KIO2 Service (Implementation)

KIO2 is a **headless API service** that locates the fault behind a failing
execution — it records a trace, computes a backward dynamic slice, and returns
**ranked suspect statements** with runtime evidence. Fix generation is **KIO7's**
job (D2.6 boundary); KIO2 hands off the slice context.

> 🔌 **Integrating KIO2 into the platform?** Start with
> [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — endpoints, the three task
> payloads with examples, operational caveats, the open input-contract decision,
> and where D2.6 and this implementation disagree.
>
> 📖 **Full technical documentation:** [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)
> — how it works, input/output, API, Docker, platform integration, and the
> Grafana/OpenTelemetry status & gaps. Component breakdown:
> [`docs/architecture/architecture.yml`](docs/architecture/architecture.yml).
> Per-requirement specs: [`docs/requirements/`](docs/requirements/).

**FocusTracer is the engine, consumed as a library** (independent tool, not
vendored here). Install it, then this package.

### Layout

```
src/kio2/        service package (contract, runner, localizer, replayer,
                 comparator, observability, kio1, service)
src/kio2/examples/  bundled failing example (dummy input)
tests/           tests
docs/requirements/  FR-KIO2-XX.md (issue-template format)
Dockerfile       independent, headless API image
```

### Run

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
> [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `ruff` + `pytest` on
> every push and PR against Python 3.11 and 3.12.

### Docker

```bash
docker build -t ai4sweng-kio2 .
docker run -p 8013:8013 ai4sweng-kio2
```

### Contract

`POST /execute` serves three task types, chosen by `task_type` in the payload
(inferred from the payload shape when omitted, so older callers keep working):

| `task_type` | Payload | Returns | FR |
|---|---|---|---|
| `fault_localization` (default) | `target_script`, `working_directory`, `functions`, … | `FaultLocalization` — ranked `suspect_lines`, `crash_state`, `confidence`, `handoff_context` | 05 |
| `replay` | `trace_path` + a start point (`seq` / `at_line` / `at_exception`) + `step_action` (`into`/`over`/`out`, `back`) | `ReplayView` — cursor, recorded state, timeline window, def-use | 02 |
| `trace_alignment` | `trace_paths`: two traces (side-by-side) or three+ (trace set) | `TraceComparison` — distance, divergences, value deltas · or matrix, reference, outlier | 03 |

`GET /tasks` lists them; a bare `{}` payload uses the bundled dummy example.

The same `POST /execute` also speaks the **KIO1 dispatch protocol**
(`workflow_id` / `step_id` / `capability` / `task` / `data` → `status` / `output`),
so the orchestrator can call KIO2 directly for `bug_localization`, `diagnosis`,
`replay` and `trace_alignment`. See [`docs/INTEGRATION.md`](docs/INTEGRATION.md) §3.
When dropped into the AI4SWENG platform, the service auto-upgrades to a full KIO
shell (NATS, capability announcements, HITL). See `docs/requirements/` for the
FR mapping and `src/kio2/README.md` for module details.
