"""KIO2 service entrypoint.

Run standalone:      python -m kio2.main         (or: uvicorn kio2.main:app)
Inside the platform: drop this package into apps/kio_shells/ so ``kio_base`` is
importable — ``make_app`` then builds the real KIO shell automatically.

A ``.env`` file at the repository root is read first (see ``.env.example``), so a
local run and ``docker compose`` take their settings from the same place.
Variables already set in the environment win over the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Set ``KEY=VALUE`` lines of ``path`` that the environment does not already define."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# Before importing the service: kio2.kio1_protocol reads KIO2_TRACE_DIR at import time.
_load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import uvicorn  # noqa: E402

from kio2.service import make_app  # noqa: E402

app = make_app()

if __name__ == "__main__":
    port = int(os.environ.get("KIO_PORT", "8102"))
    host = os.environ.get("KIO_HOST", "0.0.0.0")
    uvicorn.run("kio2.main:app", host=host, port=port, reload=False)
