# AI4SWENG-KIO2

# AI4SWENG – KIO2 Project Repository

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
| `.github/workflows/`    | GitHub Actions (automation to route issues to project columns)              |

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

Automation logic is located in:
