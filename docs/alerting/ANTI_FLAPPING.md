# Anti-Flapping Mechanism

## What is Flapping?

**Flapping** is rapid state switching (UP ↔ DOWN) caused by temporary issues like packet loss or network delays. This creates a flood of false alerts.

**Anti-flapping** prevents alert spam by requiring multiple consecutive failures before triggering notifications.

## How It Works

### 1. Failure Counter (Redis)

Each monitor has a counter stored in Redis:
```
monitor:{id}:failures = number of consecutive failures
```

- **TTL**: 1 hour (auto-cleanup)
- **Reset**: on successful check

### 2. Failure Threshold

```python
FAILURE_THRESHOLD = 2  # 2 consecutive failures = alert
```

### 3. Alert Logic

**Alert is sent when:**
1. `failure_count >= 2` (threshold reached), OR
2. Transition `OK → ERROR` on first failure (critical state change)

**Alert is suppressed when:**
- First failure occurs while monitor is already in ERROR state
- Logged as `alert_suppressed` with reason `anti_flapping`

### 4. Alert Types

**Down Alerts** (on failures):
- `timeout` - request timeout exceeded
- `connection` - connection failed
- `request` - request error
- `http_error` - HTTP 4xx/5xx response

**Recovery Alert**:
- Sent on transition `ERROR → OK`
- Indicates service has recovered

### 5. State Tracking

The `last_check_status` field tracks previous state for transition detection:

| Transition | Meaning |
|------------|---------|
| `None → True/False` | First check |
| `True → False` | Service down (may trigger immediate alert) |
| `False → True` | Recovery ✅ |
| `False → False` | Still down (increment counter) |
| `True → True` | All OK (counter reset if exists) |

## Example Scenarios

### Scenario 1: Temporary Glitch
```
Check 1: OK        → failures=0, no alert
Check 2: TIMEOUT   → failures=1, ALERT SUPPRESSED (anti-flapping)
Check 3: OK        → failures=0, RECOVERY ALERT ✅
```

### Scenario 2: Persistent Problem
```
Check 1: OK              → failures=0
Check 2: TIMEOUT         → failures=1, ALERT SUPPRESSED
Check 3: TIMEOUT         → failures=2, DOWN ALERT 🚨
Check 4: TIMEOUT         → failures=3, no new alert
Check 5: OK              → failures=0, RECOVERY ALERT ✅
```

### Scenario 3: Critical Failure
```
Check 1: OK              → failures=0
Check 2: CONNECTION ERR  → failures=1, DOWN ALERT 🚨 (OK→ERROR transition)
Check 3: CONNECTION ERR  → failures=2, no new alert
```

## Configuration

Edit threshold in [src/worker/main.py](../src/worker/main.py):

```python
FAILURE_THRESHOLD = 2  # Number of failures before alert
```

**Recommendations:**
- `1` - instant alerts, many false positives
- `2` - balanced (default)
- `3+` - fewer alerts, but may miss issues

## Redis Keys

- **Key**: `monitor:{id}:failures`
- **Value**: consecutive failure count (string)
- **TTL**: 3600 seconds (1 hour)
- **Operations**: GET, SETEX, DELETE

