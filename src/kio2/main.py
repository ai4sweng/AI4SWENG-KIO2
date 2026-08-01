"""KIO2 service entrypoint.

Run standalone:      python -m kio2.main         (or: uvicorn kio2.main:app)
Inside the platform: drop this package into apps/kio_shells/ so ``kio_base`` is
importable — ``make_app`` then builds the real KIO shell automatically.
"""

from __future__ import annotations

import os

import uvicorn

from kio2.service import make_app

app = make_app()

if __name__ == "__main__":
    port = int(os.environ.get("KIO_PORT", "8013"))
    host = os.environ.get("KIO_HOST", "0.0.0.0")
    uvicorn.run("kio2.main:app", host=host, port=port, reload=False)
