# Log Analysis Commands

Complete guide to analyzing logs using command-line tools.

## 🔧 Prerequisites

Install required tools:
```bash
# jq - JSON processor
sudo apt install jq       # Debian/Ubuntu
brew install jq           # macOS

# awk, grep - usually pre-installed on Linux/macOS
```

## 📊 Worker Logs Analysis

### Basic Statistics

**Total checks performed:**
```bash
grep -c '"event":"check_completed"' logs/worker.json
```

**Success rate:**
```bash
total=$(grep -c '"event":"check_completed"' logs/worker.json)
success=$(grep '"event":"check_completed"' logs/worker.json | grep -c '"is_success":true')
echo "scale=2; $success * 100 / $total" | bc
# Output: 95.50 (95.5%)
```

**Average response time:**
```bash
cat logs/worker.json | jq 'select(.duration_ms) | .duration_ms' | awk '{sum+=$1; n++} END {print sum/n " ms"}'
```

### Error Analysis

**All errors and warnings:**
```bash
cat logs/worker.json | jq 'select(.level=="error" or .level=="warning")'
```

**Errors by type:**
```bash
cat logs/worker.json | jq -r 'select(.level=="warning" or .level=="error") | .event' | sort | uniq -c | sort -rn
```

**Example output:**
```
  15 check_timeout
   8 check_connection_error
   3 check_request_error
```

**All timeout errors:**
```bash
cat logs/worker.json | jq 'select(.event=="check_timeout")'
```

**Connection errors with details:**
```bash
cat logs/worker.json | jq 'select(.event=="check_connection_error") | {timestamp, url, error}'
```

### Performance Analysis

**Slowest monitors (top 10):**
```bash
cat logs/worker.json | jq 'select(.duration_ms) | {url, duration_ms}' | jq -s 'sort_by(.duration_ms) | reverse | .[0:10]'
```

**Average response time by URL:**
```bash
cat logs/worker.json | jq 'select(.duration_ms and .url) | {url, duration_ms}' | \
  jq -s 'group_by(.url) | map({url: .[0].url, avg: (map(.duration_ms) | add / length), count: length}) | sort_by(.avg) | reverse'
```

**Response time percentiles:**
```bash
cat logs/worker.json | jq -r 'select(.duration_ms) | .duration_ms' | sort -n | awk '
  BEGIN { count=0 }
  { data[count++]=$1 }
  END {
    print "P50:", data[int(count*0.5)]
    print "P90:", data[int(count*0.9)]
    print "P95:", data[int(count*0.95)]
    print "P99:", data[int(count*0.99)]
  }
'
```

### Alert Analysis

**Total alerts sent:**
```bash
grep -c '"event":"alert_sent"' logs/worker.json
```

**Alerts by type:**
```bash
cat logs/worker.json | jq -r 'select(.event=="alert_sent") | .alert_type' | sort | uniq -c | sort -rn
```

**Alerts by user:**
```bash
cat logs/worker.json | jq -r 'select(.event=="alert_sent") | .user' | sort | uniq -c | sort -rn
```

**Failed alerts:**
```bash
cat logs/worker.json | jq 'select(.event=="alert_failed")'
```

### Monitor-Specific Analysis

**All events for monitor #5:**
```bash
cat logs/worker.json | jq 'select(.monitor_id==5)'
```

**Timeline for specific URL:**
```bash
cat logs/worker.json | jq 'select(.url=="https://google.com") | {timestamp, event, status_code, duration_ms}'
```

**Monitors that never succeeded:**
```bash
cat logs/worker.json | jq -r 'select(.event=="check_completed" and .is_success==false) | .url' | sort | uniq
```

### Time-Based Analysis

**Logs from last hour:**
```bash
since=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)
cat logs/worker.json | jq --arg since "$since" 'select(.timestamp >= $since)'
```

**Logs from specific time range:**
```bash
cat logs/worker.json | jq 'select(.timestamp >= "2026-02-02T10:00:00Z" and .timestamp <= "2026-02-02T11:00:00Z")'
```

**Errors grouped by hour:**
```bash
cat logs/worker.json | jq -r 'select(.level=="error") | .timestamp[0:13]' | sort | uniq -c
```

## 🌐 API Logs Analysis

### User Activity

**Total API requests:**
```bash
cat logs/api.json | jq -s 'length'
```

**Requests by event type:**
```bash
cat logs/api.json | jq -r '.event' | sort | uniq -c | sort -rn
```

**User authentications:**
```bash
cat logs/api.json | jq 'select(.event=="user_authenticated") | {timestamp, username, user_id}'
```

**Monitor creation events:**
```bash
cat logs/api.json | jq 'select(.event=="monitors_bulk_create") | {timestamp, user, count, urls}'
```

### User-Specific Activity

**All activity for user "john":**
```bash
cat logs/api.json | jq 'select(.user=="john" or .username=="john")'
```

## 💬 Telegram Logs Analysis

### Bot Commands

**All commands received:**
```bash
cat logs/telegram.json | jq 'select(.event=="command_received") | {timestamp, command, username}'
```

**Commands by type:**
```bash
cat logs/telegram.json | jq -r 'select(.event=="command_received") | .command' | sort | uniq -c
```

**Successful linkings:**
```bash
cat logs/telegram.json | jq 'select(.event=="telegram_linked") | {timestamp, username, telegram_chat_id}'
```

**Failed linking attempts:**
```bash
cat logs/telegram.json | jq 'select(.event=="username_verification_attempt")'
```

## 🔍 Advanced Queries

### Correlation Analysis

**Monitors with alerts in last 24h:**
```bash
cat logs/worker.json | jq -r 'select(.event=="alert_sent") | .monitor_id' | sort -u
```

**URLs that timeout frequently:**
```bash
cat logs/worker.json | jq -r 'select(.event=="check_timeout") | .url' | sort | uniq -c | sort -rn | head -10
```

### Multi-File Analysis

**Cross-service user activity:**
```bash
# User creates monitors via API
cat logs/api.json | jq 'select(.user=="john")'

# Then monitors are checked by worker
cat logs/worker.json | jq 'select(.monitor_id==5)'

# User receives alerts via Telegram
cat logs/telegram.json | jq 'select(.telegram_chat_id==872366593)'
```

### Real-Time Monitoring

**Follow logs in real-time:**
```bash
tail -f logs/worker.json | jq .
```

**Watch for errors:**
```bash
tail -f logs/worker.json | jq 'select(.level=="error" or .level=="warning")'
```

**Watch specific monitor:**
```bash
tail -f logs/worker.json | jq 'select(.monitor_id==5)'
```

## 📈 Reporting

### Daily Summary

Create daily report:
```bash
#!/bin/bash
DATE=$(date +%Y-%m-%d)
echo "=== Daily Report: $DATE ==="
echo ""
echo "Total checks: $(grep -c '"event":"check_completed"' logs/worker.json)"
echo "Errors: $(grep -c '"level":"error"' logs/worker.json)"
echo "Warnings: $(grep -c '"level":"warning"' logs/worker.json)"
echo "Alerts sent: $(grep -c '"event":"alert_sent"' logs/worker.json)"
echo ""
echo "Top 5 slowest monitors:"
cat logs/worker.json | jq 'select(.duration_ms) | {url, duration_ms}' | \
  jq -s 'sort_by(.duration_ms) | reverse | .[0:5]'
```

### Export to CSV

**Export checks to CSV:**
```bash
cat logs/worker.json | jq -r 'select(.event=="check_completed") | [.timestamp, .url, .status_code, .duration_ms, .is_success] | @csv' > checks.csv
```

## 🛠️ Useful Aliases

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# Log analysis shortcuts
alias log-errors='cat logs/worker.json | jq "select(.level==\"error\" or .level==\"warning\")"'
alias log-timeouts='cat logs/worker.json | jq "select(.event==\"check_timeout\")"'
alias log-alerts='cat logs/worker.json | jq "select(.event==\"alert_sent\")"'
alias log-stats='cat logs/worker.json | jq "select(.duration_ms) | .duration_ms" | awk "{sum+=\$1; n++} END {print sum/n \" ms\"}"'
alias log-watch='tail -f logs/worker.json | jq .'
```