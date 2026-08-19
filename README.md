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

> 📖 **Full technical documentation:** [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)
> — how it works, input/output, API, Docker, platform integration, and the
> Grafana/OpenTelemetry status & gaps. Per-requirement specs: [`docs/requirements/`](docs/requirements/).

**FocusTracer is the engine, consumed as a library** (independent tool, not
vendored here). Install it, then this package.

### Layout

```
src/kio2/        service package (contract, runner, localizer, observability, service)
src/kio2/examples/  bundled failing example (dummy input)
tests/           tests
docs/requirements/  FR-KIO2-XX.md (issue-template format)
Dockerfile       independent, headless API image
```

### Run

```bash
pip install -e ../../Trace/focustracer     # engine, needs >= 1.8 (or from Git — see requirements.txt)
pip install -e ".[dev]"                    # KIO2 service + pytest

# library demo:
python -c "from kio2 import localize; from kio2.dummy import dummy_input; print(localize(dummy_input()).message)"

# API service:
python -m kio2.main                        # POST /execute, GET /health/ on :8013

# lint + tests (same gates CI enforces):
ruff check .
pytest -q
```

> FocusTracer **≥ 1.8** is required: KIO2 imports `focustracer.core.{slicer,reverse,explain}`
> and the replay/alignment engine. An older install fails at import time.
> [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `ruff` + `pytest` on
> every push and PR against Python 3.11 and 3.12.

### Docker

```bash
docker build -t ai4sweng-kio2 .
docker run -p 8013:8013 ai4sweng-kio2
```

### Contract

`POST /execute` with `{"payload": {"target_script": "...", "working_directory": "...", "functions": [...]}}`
→ returns a `FaultLocalization` artifact (ranked `suspect_lines`, `crash_state`,
`confidence`, `handoff_context`). A bare `{}` payload uses the bundled dummy example.
When dropped into the AI4SWENG platform, the service auto-upgrades to a full KIO
shell (NATS, capability announcements, HITL). See `docs/requirements/` for the
FR mapping and `src/kio2/README.md` for module details.
