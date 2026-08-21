"""Execution harness — run a failing target under FocusTracer to get a trace.

KIO2 cannot localise a fault from static text alone; it needs a *recorded
execution*. This module runs the target program under FocusTracer's recorder
(via the CLI, in a subprocess for isolation) and returns the path to the
resulting schema-2.3 trace. FocusTracer records the unhandled exception into
the trace and still exits cleanly, so the crash is available for slicing.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

#: Cap on auto-discovered trace targets. Each one becomes a ``--function`` flag,
#: and Windows caps a command line at ~32 000 characters; 400 names leaves ample
#: headroom. Exceeding it is reported rather than silently truncated.
MAX_AUTO_TARGETS = 400

#: Directories that never contain the program under analysis.
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env", ".env",
    "node_modules", "site-packages", "build", "dist", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
})


class RunnerError(RuntimeError):
    """Raised when the target could not be traced."""


def discover_functions(
    target_script: str | Path,
    working_directory: str | Path = "",
    *,
    limit: int = MAX_AUTO_TARGETS,
) -> tuple[list[str], list[str]]:
    """Find the functions to trace when the caller did not name any.

    KIO2's callers know *which run failed*, not *which functions to instrument* —
    an upstream KIO hands over a failing test or a runtime log, never a function
    list. The engine, however, requires explicit function targets (file-only
    activation is not supported), and its own "trace everything" fallback only
    looks inside the entry script. A realistic entry point (``main.py`` that just
    calls into a package) defines no functions at all, so that fallback finds
    nothing and the run fails.

    This closes the gap on the KIO2 side: statically collect every function and
    method defined under the project root, entry script first.

    Returns ``(functions, notes)``. ``notes`` carries anything the caller should
    surface to a human — currently only that the limit truncated the list.
    """
    script = Path(target_script)
    root = Path(working_directory) if working_directory else script.parent
    if not root.is_dir():
        root = script.parent

    # Entry script first, then its siblings, then the rest of the tree — so a
    # truncated list keeps the code nearest the entry point.
    ordered: list[Path] = []
    if script.is_file() and script.suffix == ".py":
        ordered.append(script.resolve())
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        resolved = path.resolve()
        if resolved not in ordered:
            ordered.append(resolved)
    ordered.sort(key=lambda p: (p.parent != script.resolve().parent, str(p)))

    names: list[str] = []
    seen: set[str] = set()
    for path in ordered:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except (OSError, SyntaxError):
            continue  # unreadable or not valid Python — not our program to fix
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in seen:
                seen.add(node.name)
                names.append(node.name)

    notes: list[str] = []
    if len(names) > limit:
        notes.append(
            f"auto-discovered {len(names)} functions under {root}; traced the first "
            f"{limit} (nearest the entry point). Pass 'functions' explicitly to control this."
        )
        names = names[:limit]
    return names, notes


def _subprocess_env() -> dict[str, str]:
    """Env for the tracing subprocess, with FocusTracer guaranteed importable.

    The subprocess runs from the target's directory, so a relative PYTHONPATH
    would break. We derive FocusTracer's install location from the imported
    package and prepend it — this makes tracing work whether FocusTracer is
    pip-installed or run from a source checkout, regardless of cwd.
    """
    env = {**os.environ}
    try:
        import focustracer

        ft_parent = str(Path(focustracer.__file__).resolve().parents[1])
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (ft_parent, existing) if p)
    except Exception:
        pass
    return env


def run_trace(
    target_script: str,
    *,
    working_directory: str = "",
    functions: list[str] | None = None,
    detail: str = "detailed",
    schema_version: str = "2.3",
    output_path: str | None = None,
    timeout: float = 180.0,
    python_executable: str | None = None,
    notes: list[str] | None = None,
) -> str:
    """Trace ``target_script`` and return the path to the produced XML trace.

    Runs ``python -m focustracer run`` in a subprocess. ``working_directory``,
    if given, is used both as the process cwd and as the FocusTracer project
    root. Raises :class:`RunnerError` if no non-empty trace is produced.

    ``functions`` empty (or omitted) means *trace everything*: the targets are
    discovered from the project with :func:`discover_functions`. Pass ``notes``
    (a list) to receive any human-readable remarks about that discovery.
    """
    script = Path(target_script)
    if working_directory:
        cwd = str(Path(working_directory))
        if not script.is_absolute():
            script = Path(working_directory) / target_script
    else:
        cwd = str(script.parent) if script.parent.as_posix() else os.getcwd()

    if not script.exists():
        raise RunnerError(f"target script not found: {script}")

    if output_path is None:
        output_path = str(Path(tempfile.gettempdir()) / f"kio2_{uuid.uuid4().hex}.xml")

    targets = list(functions or [])
    if not targets:
        targets, auto_notes = discover_functions(script, working_directory or script.parent)
        if not targets:
            raise RunnerError(
                f"no functions found to trace under {working_directory or script.parent}. "
                "The engine needs at least one function target; pass 'functions' explicitly."
            )
        if notes is not None:
            notes.extend(auto_notes)

    cmd = [
        python_executable or sys.executable, "-m", "focustracer", "run",
        "--target-script", str(script),
        "--detail", detail,
        "--schema-version", schema_version,
        "--output", output_path,
    ]
    if working_directory:
        cmd += ["--project-root", str(Path(working_directory))]
    for fn in targets:
        cmd += ["--function", fn]

    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env=_subprocess_env(),
            # FocusTracer writes UTF-8 (its trace views use ▶ / Δ / ≠). Without an
            # explicit codec, `text=True` decodes with the *host* locale — cp1254 on
            # a Turkish Windows install — and the reader thread dies on the first
            # non-ASCII byte, losing the diagnostics we report in RunnerError.
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(f"tracing timed out after {timeout:.0f}s") from exc

    out = Path(output_path)
    if not out.exists() or out.stat().st_size == 0:
        raise RunnerError(
            "no trace produced. focustracer output:\n"
            + (proc.stderr or proc.stdout or "(no output)")[-800:]
        )
    return output_path
