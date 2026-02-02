# Event Reference

Complete list of all logged events in the Watchdog HTTP project.

## 🔄 Worker Events

### Lifecycle

**`startup`**
- **Level:** INFO
- **When:** Worker process starts
- **Fields:** `database_host`, `database_port`, `redis_host`, `redis_port`, `telegram_enabled`
- **Example:**
  ```json
  {"service": "worker", "event": "startup", "database_host": "database", "database_port": 5432, "redis_host": "redis", "redis_port": 6379, "telegram_enabled": true, "level": "info"}
  ```

**`worker_ready`**
- **Level:** INFO
- **When:** Worker finished initialization
- **Fields:** None
- **Example:**
  ```json
  {"service": "worker", "event": "worker_ready", "level": "info"}
  ```

**`shutdown_started`**
- **Level:** INFO
- **When:** Worker starting graceful shutdown
- **Fields:** None

**`http_client_closed`**
- **Level:** INFO
- **When:** HTTP client closed during shutdown
- **Fields:** None

**`shutdown_complete`**
- **Level:** INFO
- **When:** Worker shutdown completed
- **Fields:** None

### Scheduler

**`scheduler_started`**
- **Level:** DEBUG
- **When:** Scheduler cron job started
- **Fields:** `timestamp`
- **Example:**
  ```json
  {"service": "worker", "event": "scheduler_started", "timestamp": "2026-02-02T18:00:00.000000Z", "level": "debug"}
  ```

**`scheduler_no_monitors_due`**
- **Level:** DEBUG
- **When:** No monitors need checking
- **Fields:** None

**`scheduler_monitors_found`**
- **Level:** INFO
- **When:** Found monitors to check
- **Fields:** `count`
- **Example:**
  ```json
  {"service": "worker", "event": "scheduler_monitors_found", "count": 5, "level": "info"}
  ```

**`monitor_queued`**
- **Level:** DEBUG
- **When:** Monitor check job queued
- **Fields:** `monitor_id`, `name`, `url`
- **Example:**
  ```json
  {"service": "worker", "event": "monitor_queued", "monitor_id": 5, "name": "Google", "url": "https://google.com", "level": "debug"}
  ```

**`scheduler_completed`**
- **Level:** DEBUG
- **When:** Scheduler finished queuing jobs
- **Fields:** `queued_count`

### Monitor Checks

**`monitor_not_found`**
- **Level:** WARNING
- **When:** Monitor ID doesn't exist in database
- **Fields:** `monitor_id`
- **Example:**
  ```json
  {"service": "worker", "event": "monitor_not_found", "monitor_id": 999, "level": "warning"}
  ```

**`monitor_paused`**
- **Level:** DEBUG
- **When:** Monitor is inactive, skipping check
- **Fields:** `monitor_id`, `url`

**`check_started`**
- **Level:** DEBUG
- **When:** Starting HTTP check
- **Fields:** `monitor_id`, `url`
- **Example:**
  ```json
  {"service": "worker", "event": "check_started", "monitor_id": 5, "url": "https://google.com", "level": "debug"}
  ```

**`check_timeout`**
- **Level:** WARNING
- **When:** HTTP request timed out
- **Fields:** `monitor_id`, `url`
- **Example:**
  ```json
  {"service": "worker", "event": "check_timeout", "monitor_id": 5, "url": "https://slow-site.com", "level": "warning"}
  ```

**`check_connection_error`**
- **Level:** WARNING
- **When:** Cannot connect to host
- **Fields:** `monitor_id`, `url`, `error`
- **Example:**
  ```json
  {"service": "worker", "event": "check_connection_error", "monitor_id": 5, "url": "https://down.com", "error": "[Errno -2] Name or service not known", "level": "warning"}
  ```

**`check_request_error`**
- **Level:** ERROR
- **When:** Other HTTP request error
- **Fields:** `monitor_id`, `url`, `error`

**`check_completed`**
- **Level:** INFO
- **When:** Check finished successfully
- **Fields:** `monitor_id`, `url`, `is_success`, `status_code`, `duration_ms`, `next_check`
- **Example:**
  ```json
  {"service": "worker", "event": "check_completed", "monitor_id": 5, "url": "https://google.com", "is_success": true, "status_code": 200, "duration_ms": 150, "next_check": "2026-02-02T19:00:00+00:00", "level": "info"}
  ```

### Alerts

**`alert_monitor_not_found`**
- **Level:** WARNING
- **When:** Alert triggered for non-existent monitor
- **Fields:** `monitor_id`, `alert_type` (optional)

**`alert_skipped_no_telegram`**
- **Level:** INFO
- **When:** User has no Telegram linked
- **Fields:** `user`, `monitor_id`, `alert_type` (optional)
- **Example:**
  ```json
  {"service": "worker", "event": "alert_skipped_no_telegram", "user": "john", "monitor_id": 5, "level": "info"}
  ```

**`alert_queued`**
- **Level:** INFO
- **When:** Alert job queued
- **Fields:** `alert_type`, `monitor_id`, `status_code` (optional)
- **Example:**
  ```json
  {"service": "worker", "event": "alert_queued", "alert_type": "timeout", "monitor_id": 5, "level": "info"}
  ```

**`alert_sent`**
- **Level:** INFO
- **When:** Alert successfully sent to user
- **Fields:** `alert_type`, `user`, `monitor_id`, `monitor_name`, `url`, `error` (optional)
- **Example:**
  ```json
  {"service": "worker", "event": "alert_sent", "alert_type": "timeout", "user": "john", "monitor_id": 5, "monitor_name": "Google", "url": "https://google.com", "level": "info"}
  ```

**`alert_failed`**
- **Level:** ERROR
- **When:** Failed to send alert
- **Fields:** `alert_type`, `user`, `monitor_id`
- **Example:**
  ```json
  {"service": "worker", "event": "alert_failed", "alert_type": "timeout", "user": "john", "monitor_id": 5, "level": "error"}
  ```

## 🌐 API Events

### Lifecycle

**`startup`**
- **Level:** INFO
- **When:** API service starts
- **Fields:** `debug_mode`, `database_host`, `database_port`, `database_name`, `redis_host`, `redis_port`
- **Example:**
  ```json
  {"service": "api", "event": "startup", "debug_mode": false, "database_host": "database", "database_port": 5432, "database_name": "watchdog-http", "redis_host": "redis", "redis_port": 6379, "level": "info"}
  ```

**`shutdown`**
- **Level:** INFO
- **When:** API service shuts down
- **Fields:** None

### User Operations

**`user_registration_attempt`**
- **Level:** INFO
- **When:** User creation requested
- **Fields:** `username`
- **Example:**
  ```json
  {"service": "api", "event": "user_registration_attempt", "username": "john", "level": "info"}
  ```

**`user_authenticated`**
- **Level:** INFO
- **When:** User successfully authenticated
- **Fields:** `username`, `user_id`
- **Example:**
  ```json
  {"service": "api", "event": "user_authenticated", "username": "john", "user_id": 1, "level": "info"}
  ```

### Monitor Operations

**`monitors_bulk_create`**
- **Level:** INFO
- **When:** Multiple monitors created
- **Fields:** `user`, `user_id`, `count`, `urls`
- **Example:**
  ```json
  {"service": "api", "event": "monitors_bulk_create", "user": "john", "user_id": 1, "count": 3, "urls": ["https://google.com", "https://github.com"], "level": "info"}
  ```

## 💬 Telegram Events

### Lifecycle

**`startup`**
- **Level:** INFO
- **When:** Telegram bot starts
- **Fields:** `bot_username`
- **Example:**
  ```json
  {"service": "telegram", "event": "startup", "bot_username": "watchdog_bot", "level": "info"}
  ```

### Bot Commands

**`command_received`**
- **Level:** INFO
- **When:** User sends bot command
- **Fields:** `command`, `user_id`, `username`
- **Example:**
  ```json
  {"service": "telegram", "event": "command_received", "command": "start", "user_id": 123456789, "username": "john_doe", "level": "info"}
  ```

**`unknown_command`**
- **Level:** DEBUG
- **When:** User sends unknown command
- **Fields:** `text`, `user_id`
- **Example:**
  ```json
  {"service": "telegram", "event": "unknown_command", "text": "/unknown", "user_id": 123456789, "level": "debug"}
  ```

### Username Linking

**`username_verification_attempt`**
- **Level:** INFO
- **When:** User tries to link account
- **Fields:** `username`, `user_id`, `telegram_username`
- **Example:**
  ```json
  {"service": "telegram", "event": "username_verification_attempt", "username": "john", "user_id": 123456789, "telegram_username": "john_doe", "level": "info"}
  ```

**`telegram_linked`**
- **Level:** INFO
- **When:** Account successfully linked
- **Fields:** `username`, `user_id`, `telegram_chat_id`, `telegram_username`
- **Example:**
  ```json
  {"service": "telegram", "event": "telegram_linked", "username": "john", "user_id": 1, "telegram_chat_id": 123456789, "telegram_username": "john_doe", "level": "info"}
  ```

## 📊 Event Frequency

| Event | Frequency | Service |
|-------|-----------|---------|
| `check_completed` | Every minute per monitor | Worker |
| `scheduler_monitors_found` | Every minute | Worker |
| `alert_sent` | On errors only | Worker |
| `user_authenticated` | Per API request | API |
| `command_received` | Per bot command | Telegram |
| `startup` | Once per service start | All |

## 🔗 Event Flow Examples

### Successful Monitor Check
```
1. scheduler_started
2. scheduler_monitors_found (count: 3)
3. monitor_queued (monitor_id: 1)
4. monitor_queued (monitor_id: 2)
5. monitor_queued (monitor_id: 3)
6. check_started (monitor_id: 1)
7. check_completed (monitor_id: 1, status: 200)
8. check_started (monitor_id: 2)
9. check_completed (monitor_id: 2, status: 200)
... etc
```

### Failed Check with Alert
```
1. check_started (monitor_id: 5)
2. check_timeout (monitor_id: 5)
3. check_completed (monitor_id: 5, is_success: false)
4. alert_queued (alert_type: timeout)
5. alert_sent (user: john, alert_type: timeout)
```

### User Registration and Linking
```
1. user_registration_attempt (username: john)
2. user_created (user_id: 1, username: john)
3. command_received (command: start)
4. username_verification_attempt (username: john)
5. telegram_linked (username: john, telegram_chat_id: 123456789)
```
