# KIO2 — independent, headless API service (Bug Locate & Fix).
# Builds a self-contained image: FocusTracer engine (from source) + the KIO2
# service. Exposes the KIO contract on :8102 (POST /execute, GET /health/).
#
#   docker build -t ai4sweng-kio2 .
#   docker run -p 8102:8102 ai4sweng-kio2
#   curl -XPOST localhost:8102/execute -H 'content-type: application/json' -d '{"payload":{}}'
#
FROM python:3.12-slim

WORKDIR /app

# git is needed: pip installs FocusTracer from its public GitHub repository
# (declared in pyproject.toml). The slim image has no git.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

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
