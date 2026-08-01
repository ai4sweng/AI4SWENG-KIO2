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

RUN pip install --no-cache-dir --upgrade pip

# FocusTracer = independent engine consumed as a library (adjust org/ref as needed).
# For offline/air-gapped builds, replace this with a COPY of a local checkout +
# `pip install ./focustracer`.
ARG FOCUSTRACER_REF=git+https://github.com/BitnetTR/focustracer@main
RUN pip install --no-cache-dir "focustracer @ ${FOCUSTRACER_REF}"

# Install the KIO2 service (focustracer already satisfied above).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV KIO_PORT=8013 KIO_HOST=0.0.0.0
EXPOSE 8013

CMD ["python", "-m", "uvicorn", "kio2.main:app", "--host", "0.0.0.0", "--port", "8013"]
