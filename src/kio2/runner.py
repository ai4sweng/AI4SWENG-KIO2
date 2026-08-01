"""Execution harness — run a failing target under FocusTracer to get a trace.

KIO2 cannot localise a fault from static text alone; it needs a *recorded
execution*. This module runs the target program under FocusTracer's recorder
(via the CLI, in a subprocess for isolation) and returns the path to the
resulting schema-2.3 trace. FocusTracer records the unhandled exception into
the trace and still exits cleanly, so the crash is available for slicing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


class RunnerError(RuntimeError):
    """Raised when the target could not be traced."""


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
) -> str:
    """Trace ``target_script`` and return the path to the produced XML trace.

    Runs ``python -m focustracer run`` in a subprocess. ``working_directory``,
    if given, is used both as the process cwd and as the FocusTracer project
    root. Raises :class:`RunnerError` if no non-empty trace is produced.
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

    cmd = [
        python_executable or sys.executable, "-m", "focustracer", "run",
        "--target-script", str(script),
        "--detail", detail,
        "--schema-version", schema_version,
        "--output", output_path,
    ]
    if working_directory:
        cmd += ["--project-root", str(Path(working_directory))]
    for fn in functions or []:
        cmd += ["--function", fn]

    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env=_subprocess_env(),
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
