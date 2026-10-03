"""KIO2 Playground — a browser front end over the KIO1 job contract.

The page (``playground/index.html``) drives the same ``POST /jobs`` and
``GET /jobs/{job_id}`` a KIO1 dispatcher uses, so what it shows is exactly what
an orchestrator receives. This module only adds what a browser cannot do on its
own:

- ``GET /playground`` — the page itself;
- ``GET /playground/examples`` — the bundled example programs, with their source;
- ``POST /playground/snippets`` — store pasted code as a script on this machine
  and return the ``file://`` references a job request needs.

Pasted code is **executed** by the next job, and the service has no
authentication (docs/INTEGRATION.md §7). Snippets are therefore refused unless
``KIO2_PLAYGROUND_SNIPPETS`` is set; enable it only on a machine you trust, e.g.
a local demo.
"""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .openapi_examples import EXAMPLES_DIR, FAILING, PASSING

PAGE = Path(__file__).resolve().parent / "playground" / "index.html"

#: Largest snippet accepted, in bytes. A demo program is a few kilobytes.
MAX_SNIPPET_BYTES = 256 * 1024

#: Module level: with ``from __future__ import annotations`` FastAPI resolves the
#: handler's annotations against this module's globals (see service.JobRequest).
SnippetBody = Annotated[dict[str, Any], Body()]

_FILENAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}\.py$")

#: The bundled examples, in the order the page lists them.
EXAMPLES = [
    {
        "name": FAILING,
        "title": "Failing example",
        "description": "No item is in stock, so the average divides by zero.",
    },
    {
        "name": PASSING,
        "title": "Corrected example",
        "description": "The same program with a guard for an empty cart.",
    },
]


def snippets_enabled() -> bool:
    return os.environ.get("KIO2_PLAYGROUND_SNIPPETS", "").strip().lower() in ("1", "true", "yes", "on")


def snippet_root() -> Path:
    """Where pasted programs are written: one folder per snippet."""
    return Path(tempfile.gettempdir()).resolve() / "kio2_playground"


def save_snippet(code: str, filename: str = "main.py") -> dict[str, Any]:
    """Write ``code`` to a fresh folder; return the job ``data`` references for it."""
    if not _FILENAME.match(filename):
        raise ValueError("filename must be a Python file name such as main.py")
    if not code.strip():
        raise ValueError("code is empty")
    if len(code.encode("utf-8")) > MAX_SNIPPET_BYTES:
        raise ValueError(f"code is larger than {MAX_SNIPPET_BYTES // 1024} KB")

    folder = snippet_root() / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True)
    script = folder / filename
    script.write_text(code, encoding="utf-8")
    return {
        "repository": {"uri": folder.as_uri()},
        "entry_point": {"uri": script.as_uri()},
    }


def register(app: FastAPI) -> None:
    """Add the playground routes to ``app``."""

    @app.get("/playground", tags=["Playground"], summary="Open the KIO2 Playground",
             response_class=HTMLResponse)
    async def playground_page() -> HTMLResponse:
        return HTMLResponse(PAGE.read_text(encoding="utf-8"))

    @app.get("/playground/examples", tags=["Playground"], summary="Bundled example programs")
    async def playground_examples() -> dict[str, Any]:
        """The examples with their source and the references a job request needs."""
        return {
            "snippets_enabled": snippets_enabled(),
            "examples": [
                {
                    **ex,
                    "code": (EXAMPLES_DIR / ex["name"]).read_text(encoding="utf-8"),
                    "data": {
                        "repository": {"uri": EXAMPLES_DIR.as_uri()},
                        "entry_point": {"uri": (EXAMPLES_DIR / ex["name"]).as_uri()},
                    },
                }
                for ex in EXAMPLES
            ],
        }

    @app.post("/playground/snippets", tags=["Playground"], summary="Store pasted code to run")
    async def playground_snippet(body: SnippetBody) -> dict[str, Any]:
        """Save pasted code as a script; refused unless ``KIO2_PLAYGROUND_SNIPPETS`` is set."""
        if not snippets_enabled():
            raise HTTPException(
                status_code=403,
                detail="Running pasted code is off. Start KIO2 with KIO2_PLAYGROUND_SNIPPETS=1 "
                       "on a machine you trust to enable it.",
            )
        try:
            return save_snippet(str(body.get("code") or ""), str(body.get("filename") or "main.py"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
