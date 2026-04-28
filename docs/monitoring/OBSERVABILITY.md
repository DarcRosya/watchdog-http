# Observability Stack

Watchdog ships a Prometheus + Grafana stack with a pre-provisioned dashboard for
worker health, queue depth, checks, and API latency.

---

## Services and URLs

| Service | URL | Notes |
| :--- | :--- | :--- |
| Grafana | http://localhost:3000 | Default login: `admin` / `admin` (override via `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`) |
| Prometheus | http://localhost:9090 | Scrapes API `/metrics` and Pushgateway |
| Pushgateway | http://localhost:9091 | Worker metrics ingestion |

---

## Provisioning

Grafana is provisioned from the repository on container start:

- Dashboards provider: [monitoring/grafana/provisioning/dashboards/dashboards.yml](monitoring/grafana/provisioning/dashboards/dashboards.yml)
- Dashboard JSON: [monitoring/grafana/provisioning/dashboards/watchdog_dashboard.json](monitoring/grafana/provisioning/dashboards/watchdog_dashboard.json)
- Prometheus datasource: [monitoring/grafana/provisioning/datasources/datasource.yml](monitoring/grafana/provisioning/datasources/datasource.yml)

The provider polls for updates every 10 seconds, so edits to the JSON will be
picked up without a restart. When exporting dashboards from Grafana, remove any
fixed `time` block to avoid locking the dashboard to an absolute range.

---

## Key Metrics

- `http_checks_total{monitor_id,status_code,is_success}`: total HTTP checks.
- `http_check_duration_seconds{monitor_id}`: per-monitor latency histogram.
- `worker_jobs_total{worker_type,status}`: completed jobs by worker and status.
- `scheduler_backlog`: number of due monitors waiting to be scheduled.
- `arq_queue_depth{queue_name}`: queue depth for monitoring and alerting.
- `push_time_seconds{job="arq_worker"}`: last Pushgateway update time.
- `http_requests_total{job="watchdog_api"}`: FastAPI request throughput.
- `http_request_duration_highr_seconds_bucket` or `http_request_duration_seconds_bucket`: API latency histograms.

---

## Troubleshooting

- Empty panels: check the dashboard time range and ensure metrics are within it.
- No worker metrics: verify Pushgateway is reachable and Prometheus can scrape it.
- No API metrics: open Prometheus targets and confirm `/metrics` is up on the app.
