# KIO2 — independent, headless API service (Bug Locate & Fix).
# Builds a self-contained image: FocusTracer engine (from source) + the KIO2
# service. Exposes the KIO contract on :8013 (POST /execute, GET /health/).
#
#   docker build -t ai4sweng-kio2 .
#   docker run -p 8013:8013 ai4sweng-kio2
#   curl -XPOST localhost:8013/execute -H 'content-type: application/json' -d '{"payload":{}}'
#
FROM python:3.12-slim

WORKDIR /app

# git is needed to pip-install FocusTracer from its repo (slim image has none).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

# FocusTracer = independent engine consumed as a library (adjust org/ref as needed).
# For offline/air-gapped builds or a private repo, replace this with a COPY of a
# local checkout + `pip install ./focustracer` (no git/network needed).
ARG FOCUSTRACER_REF=git+https://github.com/BitnetTR/focustracer.git@master
RUN pip install --no-cache-dir "focustracer @ ${FOCUSTRACER_REF}"

# Install the KIO2 service (focustracer already satisfied above).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# 8102 is the port KIO1's dispatch registry has for KIO2 (config.json), following
# its per-KIO scheme (KIO2 -> 8102, KIO10 -> 8110). Override with -e KIO_PORT=...
ENV KIO_PORT=8102 KIO_HOST=0.0.0.0
EXPOSE 8102

# Go through the package entrypoint, which reads KIO_PORT / KIO_HOST. Calling
# uvicorn directly with a hard-coded --port silently ignored -e KIO_PORT.
CMD ["python", "-m", "kio2.main"]
