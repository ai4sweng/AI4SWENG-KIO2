# KIO2 — OpenTelemetry Integration Handoff

Brief for the agent wiring the AI4SWENG program-wide observability (OTEL → Grafana).
KIO2's code is already instrumented; this document is only about **connecting the
exporter/collector**, which KIO2 deliberately leaves to the host.

## What KIO2 already emits (do not re-instrument)

File: `kio2/observability.py`. It talks to the **global** OpenTelemetry API
providers (`opentelemetry.trace.get_tracer`, `opentelemetry.metrics.get_meter`).
If `opentelemetry` isn't installed, every call is a no-op.

**Span** (per localization run): `kio2.localize`
- attributes: `kio2.session_id`, `kio2.target`, `kio2.status`, `kio2.confidence`, `kio2.suspect_count`

**Metrics** (meter name `kio2`), all carrying a `status` attribute (`DONE` / `REVIEW_REQUIRED` / `FAILED`):
- `kio2.localization.duration` — histogram, unit `ms`
- `kio2.localization.suspect_count` — histogram, unit `1`
- `kio2.localization.confidence` — histogram, `0..1`
- `kio2.localization.runs` — counter

Integration seam: the service handler wraps each run in
`observability.localization_span(session_id, target)`; nothing else needs touching
in KIO2 to get telemetry.

## What the OTEL agent needs to do

1. **Dependencies** in KIO2's runtime env: `opentelemetry-sdk`,
   `opentelemetry-exporter-otlp` (API comes transitively).
2. **Bootstrap the SDK** at process start (before serving): configure a
   `TracerProvider` + `MeterProvider` with an OTLP exporter pointing at the
   program collector. Prefer env-driven auto-config to match the other KIOs:
   - `OTEL_SERVICE_NAME=kio2`
   - `OTEL_EXPORTER_OTLP_ENDPOINT=<collector>`
   - `OTEL_RESOURCE_ATTRIBUTES=service.name=kio2,kio.id=kio2,<program-standard attrs>`
   - a `PeriodicExportingMetricReader` for metrics.
3. **Resource attributes**: align `service.name` / `kio.id` and any program-wide
   labels with the convention the other KIOs already use, so KIO2 shows up
   consistently on the shared Grafana dashboards.
4. **docker-compose / deployment**: add the collector env vars to the KIO2 service
   (standalone: `python -m kio2.main`; platform: the `apps/kio_shells/` shell).
5. **Ordering note**: `observability.py` obtains tracer/meter at import. The OTel
   API returns lazy proxies, so setting the SDK providers at process start works
   even if it happens after import — but please verify a metric actually lands in
   the collector (quick smoke: run one localization, confirm
   `kio2.localization.runs` increments in Grafana).

## Quick local verification

```bash
# with the SDK + OTLP configured via env and a collector reachable:
python -c "from kio2 import localize; from kio2.dummy import dummy_input; localize(dummy_input())"
# → expect one `kio2.localize` span and a `kio2.localization.*` metric sample
```

## Boundaries

- KIO2 owns only its own emission points (above). Collector, exporter, sampling,
  dashboards, and cross-KIO label conventions are the observability layer's call.
- No change to KIO2's fault-localization logic is needed for observability.
