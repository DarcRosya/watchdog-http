# Logging Documentation

Complete documentation for structured logging in Watchdog HTTP.

## 📚 Documentation Structure

1. **[Analysis Commands](./analysis.md)** — Practical log analysis
   - Worker log queries
   - API log queries
   - Telegram log queries
   - Performance analysis
   - Real-time monitoring
   - Reporting scripts

2. **[Event Reference](./events.md)** — Complete event catalog
   - Worker events
   - API events
   - Telegram events
   - Event frequency
   - Event flow examples

## ⚙️ Configuration

**File logging is DISABLED by default.** To enable:

```bash
# Add to .env file
ENABLE_FILE_LOGGING=true
```

## 🚀 Quick Start

### View Recent Logs

```bash
# Worker (main activity)
tail -20 logs/worker.json | jq .

# API
tail -20 logs/api.json | jq .

# Telegram
tail -20 logs/telegram.json | jq .
```

### Find Errors

```bash
cat logs/worker.json | jq 'select(.level=="error" or .level=="warning")'
```

### Monitor in Real-Time

```bash
tail -f logs/worker.json | jq .
```

## 📊 Log Files

| File | Purpose | Volume |
|------|---------|--------|
| `api.json` | HTTP requests, user operations | Low |
| `worker.json` | Monitor checks, alerts | High |
| `telegram.json` | Bot commands, user linking | Low |

## 🔗 Key Features

- **Structured Format:** NDJSON (Newline Delimited JSON)
- **Machine-Readable:** Easy parsing with `jq`, `awk`, `grep`
- **Auto-Rotation:** 10MB max, 5 backups
- **Multi-Service:** Separate files per service
- **Rich Context:** Every log includes service, timestamp, level, event
- **Security:** No passwords, API keys, or sensitive data

## 🛠️ Common Tasks

### Performance Analysis
```bash
# Average response time
cat logs/worker.json | jq 'select(.duration_ms) | .duration_ms' | awk '{sum+=$1; n++} END {print sum/n " ms"}'

# Slowest monitors
cat logs/worker.json | jq 'select(.duration_ms) | {url, duration_ms}' | jq -s 'sort_by(.duration_ms) | reverse | .[0:10]'
```

### Error Investigation
```bash
# All timeouts
cat logs/worker.json | jq 'select(.event=="check_timeout")'

# Connection errors
cat logs/worker.json | jq 'select(.event=="check_connection_error")'

# Failed alerts
cat logs/worker.json | jq 'select(.event=="alert_failed")'
```

### User Activity
```bash
# User logins
cat logs/api.json | jq 'select(.event=="user_authenticated")'

# Bot commands
cat logs/telegram.json | jq 'select(.event=="command_received")'

# Successful linkings
cat logs/telegram.json | jq 'select(.event=="telegram_linked")'
```

## 📈 Integration

Logs can be integrated with:

- **ELK Stack** (Elasticsearch, Logstash, Kibana)
- **Grafana Loki**
- **AWS CloudWatch**
- **Datadog**
- **Splunk**
- **Custom dashboards** using APIs

All support NDJSON format natively.
