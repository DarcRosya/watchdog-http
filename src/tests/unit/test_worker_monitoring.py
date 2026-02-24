import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import Response

from src.worker.monitoring import (
    check_monitor,
    get_monitor_config,
    execute_http_check,
    check_ssl_expiry,
    process_alerting,
    HttpCheckResult,
    FAILURE_THRESHOLD,
)
from src.worker.scheduler import scheduler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "url": "https://example.com",
        "method": "GET",
        "headers": {},
        "body": None,
        "is_active": True,
        "name": "Test Monitor",
        "user_id": 1,
        "username": "test_user",
        "telegram_chat_id": 12345,
    }
    base.update(overrides)
    return base


def _make_redis(initial: dict | None = None) -> AsyncMock:
    """Redis mock backed by an in-memory dict for predictable key lookups."""
    store: dict = {} if initial is None else dict(initial)
    redis = AsyncMock()

    async def _get(key):
        return store.get(key)

    async def _setex(key, ttl, value):
        store[key] = value.encode() if isinstance(value, str) else value

    async def _set_cmd(key, value, **kw):
        store[key] = value.encode() if isinstance(value, str) else value
        return True

    async def _delete(*keys):
        for k in keys:
            store.pop(k, None)

    async def _exists(key):
        return 1 if key in store else 0

    redis.get = AsyncMock(side_effect=_get)
    redis.setex = AsyncMock(side_effect=_setex)
    redis.set = AsyncMock(side_effect=_set_cmd)
    redis.delete = AsyncMock(side_effect=_delete)
    redis.exists = AsyncMock(side_effect=_exists)
    redis.zscore = AsyncMock(return_value=None)
    redis.zadd = AsyncMock()
    redis.zrem = AsyncMock()
    redis.enqueue_job = AsyncMock()
    redis.zcount = AsyncMock(return_value=0)
    redis.zrangebyscore = AsyncMock(return_value=[])
    return redis


def _make_session_factory():
    """Return (factory, mock_session). Factory yields the same session on each call."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session


def _http_client(status_code: int = 200) -> AsyncMock:
    mock_resp = MagicMock(spec=Response)
    mock_resp.status_code = status_code
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(return_value=mock_resp)
    return client


def _failing_http_client(exc: Exception) -> AsyncMock:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(side_effect=exc)
    return client


def _ctx(redis, http_client, session_factory) -> dict:
    return {
        "http_client": http_client,
        "session_factory": session_factory,
        "redis": redis,
    }


def _make_result(**overrides) -> HttpCheckResult:
    """Create an HttpCheckResult with sensible defaults."""
    defaults = {
        "start_time": datetime.now(timezone.utc),
        "duration_ms": 42,
        "status_code": 200,
        "is_success": True,
        "error_message": None,
        "alert_type": None,
    }
    defaults.update(overrides)
    return HttpCheckResult(**defaults)


# ---------------------------------------------------------------------------
# Tests: get_monitor_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMonitorConfig:

    async def test_returns_config_from_redis_cache(self):
        monitor_id = 1
        expected = _config()
        redis = _make_redis(
            {f"monitor:{monitor_id}:config": json.dumps(expected).encode()}
        )
        factory, _ = _make_session_factory()

        result = await get_monitor_config(redis, factory, monitor_id)

        assert result["url"] == "https://example.com"
        assert result["method"] == "GET"

    async def test_returns_skipped_when_paused_in_cache(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(is_active=False)
                ).encode()
            }
        )
        factory, _ = _make_session_factory()

        result = await get_monitor_config(redis, factory, monitor_id)

        assert result == {"status": "skipped", "reason": "paused"}

    async def test_returns_skipped_when_monitor_not_in_db(self):
        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = None
        redis = _make_redis({})

        result = await get_monitor_config(redis, factory, monitor_id=999)

        assert result == {"status": "skipped", "reason": "not_found"}

    async def test_falls_back_to_db_and_caches(self):
        from src.models.monitor import Monitor as MonitorModel
        from src.models.user import User as UserModel

        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.url = "https://db.example.com"
        mock_monitor.method = "POST"
        mock_monitor.headers = {"X-Key": "val"}
        mock_monitor.body = None
        mock_monitor.name = "DB Mon"
        mock_monitor.is_active = True
        mock_monitor.user_id = 5
        mock_monitor.interval = 120

        mock_user = MagicMock(spec=UserModel)
        mock_user.username = "db_user"
        mock_user.telegram_chat_id = 777

        factory, mock_session = _make_session_factory()
        mock_session.get.side_effect = [mock_monitor, mock_user]

        redis = _make_redis({})
        result = await get_monitor_config(redis, factory, monitor_id=10)

        assert result["url"] == "https://db.example.com"
        assert result["method"] == "POST"
        assert result["username"] == "db_user"
        # Verify it was cached in Redis
        redis.setex.assert_called()

    async def test_returns_skipped_when_paused_in_db(self):
        from src.models.monitor import Monitor as MonitorModel

        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.is_active = False

        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = mock_monitor
        redis = _make_redis({})

        result = await get_monitor_config(redis, factory, monitor_id=33)

        assert result == {"status": "skipped", "reason": "paused"}


# ---------------------------------------------------------------------------
# Tests: execute_http_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteHttpCheck:

    async def test_success_200(self):
        config = _config()
        client = _http_client(200)

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is True
        assert result.status_code == 200
        assert result.alert_type is None
        assert result.error_message is None
        assert result.duration_ms >= 0

    async def test_http_error_500(self):
        config = _config()
        client = _http_client(500)

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is False
        assert result.status_code == 500
        assert result.alert_type is None  # HTTP errors don't set alert_type

    async def test_timeout_sets_alert_type(self):
        config = _config()
        client = _failing_http_client(httpx.TimeoutException("timed out"))

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is False
        assert result.alert_type == "timeout"
        assert "Timeout" in result.error_message

    async def test_connect_error_sets_alert_type(self):
        config = _config()
        client = _failing_http_client(httpx.ConnectError("refused"))

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is False
        assert result.alert_type == "connection"

    async def test_request_error_sets_alert_type(self):
        config = _config()
        client = _failing_http_client(httpx.RequestError("bad"))

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is False
        assert result.alert_type == "request"

    async def test_local_protocol_error_sets_request_type(self):
        config = _config()
        client = _failing_http_client(httpx.LocalProtocolError("bad headers"))

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is False
        assert result.alert_type == "request"
        assert "Protocol error" in result.error_message

    async def test_post_with_body_sends_content(self):
        config = _config(method="POST", body="payload", headers={"X-T": "1"})
        client = _http_client(201)

        result = await execute_http_check(client, config, monitor_id=1)

        assert result.is_success is True
        _, kwargs = client.request.call_args
        assert kwargs["content"] == b"payload"
        assert kwargs["method"] == "POST"

    async def test_get_does_not_send_body(self):
        config = _config(method="GET", body=None)
        client = _http_client(200)

        await execute_http_check(client, config, monitor_id=1)

        _, kwargs = client.request.call_args
        assert "content" not in kwargs


# ---------------------------------------------------------------------------
# Tests: check_ssl_expiry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckSslExpiry:

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_queues_alert_when_cert_expires_soon(self, mock_ssl):
        mock_ssl.return_value = 3
        monitor_id = 1
        redis = _make_redis({})
        config = _config(url="https://example.com")

        await check_ssl_expiry(redis, monitor_id, config)

        mock_ssl.assert_awaited_once_with("https://example.com")
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 1
        assert ssl_calls[0][0][6] == 3  # days_left

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_no_alert_when_cert_ok(self, mock_ssl):
        mock_ssl.return_value = 90
        redis = _make_redis({})

        await check_ssl_expiry(redis, 1, _config(url="https://safe.com"))

        redis.enqueue_job.assert_not_called()

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_skipped_for_http(self, mock_ssl):
        redis = _make_redis({})

        await check_ssl_expiry(redis, 1, _config(url="http://plain.com"))

        mock_ssl.assert_not_called()

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_runs_only_once_per_day(self, mock_ssl):
        redis = _make_redis({"monitor:1:ssl_checked_today": b"1"})

        await check_ssl_expiry(redis, 1, _config(url="https://example.com"))

        mock_ssl.assert_not_called()

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_no_duplicate_alert_within_24h(self, mock_ssl):
        mock_ssl.return_value = 2
        redis = _make_redis({"monitor:1:ssl_alert_sent": b"1"})

        await check_ssl_expiry(redis, 1, _config(url="https://example.com"))

        mock_ssl.assert_awaited_once()
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 0

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_handles_none_from_ssl_checker(self, mock_ssl):
        mock_ssl.return_value = None
        redis = _make_redis({})

        await check_ssl_expiry(redis, 1, _config(url="https://example.com"))

        redis.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: process_alerting
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessAlerting:

    async def test_resets_failures_on_success(self):
        redis = _make_redis({"monitor:1:failures": b"3"})
        result = _make_result(is_success=True)
        config = _config()

        await process_alerting(redis, 1, config, result, None, None)

        # failure key should be deleted
        redis.delete.assert_called()

    async def test_recovery_alert_sent_on_state_transition(self):
        recent_ts = str(int(datetime.now(timezone.utc).timestamp()) - 30)
        redis = _make_redis({})
        result = _make_result(is_success=True)
        config = _config()

        await process_alerting(
            redis,
            1,
            config,
            result,
            previous_status=False,
            old_timestamp_raw=recent_ts.encode(),
        )

        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_alert_recovery"

    async def test_recovery_suppressed_when_no_timestamp(self):
        redis = _make_redis({})
        result = _make_result(is_success=True)

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=False,
            old_timestamp_raw=None,
        )

        redis.enqueue_job.assert_not_called()

    async def test_recovery_suppressed_when_stale_timestamp(self):
        stale_ts = str(int(datetime.now(timezone.utc).timestamp()) - 7200)
        redis = _make_redis({})
        result = _make_result(is_success=True)

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=False,
            old_timestamp_raw=stale_ts.encode(),
        )

        redis.enqueue_job.assert_not_called()

    async def test_failure_increments_counter(self):
        redis = _make_redis({})
        result = _make_result(is_success=False, status_code=500)

        await process_alerting(redis, 1, _config(), result, None, None)

        # Should have set failure count = 1
        redis.setex.assert_called()

    async def test_alert_on_first_failure_after_ok(self):
        redis = _make_redis({})
        result = _make_result(is_success=False, status_code=500)

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=True,
            old_timestamp_raw=None,
        )

        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_alert_http_error"

    async def test_alert_suppressed_below_threshold(self):
        redis = _make_redis({})
        result = _make_result(is_success=False, status_code=503)

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=None,  # no prior state
            old_timestamp_raw=None,
        )

        # failure_count=1 < threshold=2 and no prior OK state → suppressed
        redis.enqueue_job.assert_not_called()

    async def test_alert_fires_at_threshold(self):
        redis = _make_redis({"monitor:1:failures": b"1"})  # already 1 failure
        result = _make_result(is_success=False, status_code=500)

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=None,
            old_timestamp_raw=None,
        )

        redis.enqueue_job.assert_called_once()

    async def test_exception_alert_uses_alert_type(self):
        redis = _make_redis({})
        result = _make_result(
            is_success=False,
            status_code=None,
            alert_type="timeout",
            error_message="timed out",
        )

        await process_alerting(
            redis,
            1,
            _config(),
            result,
            previous_status=True,
            old_timestamp_raw=None,
        )

        args = redis.enqueue_job.call_args[0]
        assert args[0] == "send_alert_exception"
        assert args[6] == "timeout"


# ---------------------------------------------------------------------------
# Tests: check_monitor (integration of all steps)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckMonitor:

    async def test_skipped_when_monitor_is_paused(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(is_active=False)
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, AsyncMock(spec=httpx.AsyncClient), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result == {"status": "skipped", "reason": "paused"}
        ctx["http_client"].request.assert_not_called()

    async def test_success_200_persists_log_and_returns_completed(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
            }
        )
        factory, mock_session = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["status"] == "completed"
        assert result["is_success"] is True
        assert result["status_code"] == 200
        assert result["monitor_id"] == monitor_id
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    async def test_http_error_immediately_alerts_on_first_failure_after_ok(self):
        # previous_status=True, failure_count=1 → alert fires straight away
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(500), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_alert_http_error"

    async def test_http_error_suppressed_on_first_failure_with_no_prior_state(self):
        # previous_status=None → anti-flapping: count=1 < threshold=2, no alert
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(503), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        redis.enqueue_job.assert_not_called()

    async def test_http_error_alerts_when_failure_count_reaches_threshold(self):
        # failure already stored once; this check brings count to 2 → threshold reached
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:failures": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(500), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        redis.enqueue_job.assert_called_once()

    async def test_timeout_queues_exception_alert_with_correct_type(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(
            redis, _failing_http_client(httpx.TimeoutException("timed out")), factory
        )

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        redis.enqueue_job.assert_called_once()
        args = redis.enqueue_job.call_args[0]
        assert args[0] == "send_alert_exception"
        assert args[6] == "timeout"

    async def test_connect_error_queues_exception_alert_with_correct_type(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _failing_http_client(httpx.ConnectError("refused")), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        args = redis.enqueue_job.call_args[0]
        assert args[0] == "send_alert_exception"
        assert args[6] == "connection"

    async def test_recovery_alert_queued_after_ok_following_recent_failure(self):
        # previous_status=False + recent timestamp → recovery
        monitor_id = 1
        recent_ts = str(int(datetime.now(timezone.utc).timestamp()) - 60)
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"0",
                f"monitor:{monitor_id}:last_check_time": recent_ts.encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is True
        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_alert_recovery"

    async def test_recovery_suppressed_when_no_previous_timestamp(self):
        # previous_status=False but no last_check_time → first check after worker restart
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"0",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is True
        redis.enqueue_job.assert_not_called()

    async def test_recovery_suppressed_when_last_check_was_too_old(self):
        # last_check_time > 1 hour ago → stale state, suppress recovery
        monitor_id = 1
        stale_ts = str(int(datetime.now(timezone.utc).timestamp()) - 7200)
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"0",
                f"monitor:{monitor_id}:last_check_time": stale_ts.encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is True
        redis.enqueue_job.assert_not_called()

    async def test_still_enqueues_alert_when_telegram_chat_id_is_none(self):
        # Monitoring worker always enqueues; the alerting worker handles the
        # "no_telegram" skip when it receives chat_id=None.
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(telegram_chat_id=None)
                ).encode(),
                f"monitor:{monitor_id}:state": b"1",  # was OK, now failing → alert
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(500), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        assert result["status"] == "completed"
        redis.enqueue_job.assert_called_once()  # still queued, alerting worker skips it

    async def test_falls_back_to_db_when_config_not_in_redis(self):
        from src.models.monitor import Monitor as MonitorModel
        from src.models.user import User as UserModel

        monitor_id = 99
        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.url = "https://db-fallback.com"
        mock_monitor.method = "GET"
        mock_monitor.headers = {}
        mock_monitor.body = None
        mock_monitor.name = "DB Monitor"
        mock_monitor.is_active = True
        mock_monitor.user_id = 1

        mock_user = MagicMock(spec=UserModel)
        mock_user.username = "fallback_user"
        mock_user.telegram_chat_id = None

        factory, mock_session = _make_session_factory()
        mock_session.get.side_effect = [mock_monitor, mock_user]

        redis = _make_redis({})
        ctx = _ctx(redis, _http_client(200), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["status"] == "completed"
        assert result["is_success"] is True

    async def test_db_fallback_returns_skipped_when_monitor_not_found(self):
        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = None

        redis = _make_redis({})
        ctx = _ctx(redis, AsyncMock(spec=httpx.AsyncClient), factory)

        result = await check_monitor(ctx, monitor_id=99999)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_found"

    async def test_db_fallback_returns_skipped_when_monitor_is_paused_in_db(self):
        from src.models.monitor import Monitor as MonitorModel

        monitor_id = 33
        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.is_active = False

        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = mock_monitor

        redis = _make_redis({})
        ctx = _ctx(redis, AsyncMock(spec=httpx.AsyncClient), factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["status"] == "skipped"
        assert result["reason"] == "paused"

    async def test_sends_headers_and_body_for_post(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(method="POST", headers={"X-Test": "1"}, body="payload")
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        client = _http_client(200)
        ctx = _ctx(redis, client, factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["status"] == "completed"
        # Ensure request was called with headers and content
        client.request.assert_awaited()
        _, kwargs = client.request.call_args
        assert kwargs["method"] == "POST"
        assert kwargs["headers"]["X-Test"] == "1"
        assert kwargs["content"] == b"payload"

    async def test_get_with_headers_no_body(self):
        monitor_id = 2
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(method="GET", headers={"X-Foo": "bar"}, body=None)
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        client = _http_client(200)
        ctx = _ctx(redis, client, factory)

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["status"] == "completed"
        client.request.assert_awaited()
        _, kwargs = client.request.call_args
        assert kwargs["method"] == "GET"
        assert kwargs["headers"]["X-Foo"] == "bar"
        assert "content" not in kwargs

    async def test_local_protocol_error_queues_request_type(self):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(_config()).encode(),
                f"monitor:{monitor_id}:state": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(
            redis,
            _failing_http_client(httpx.LocalProtocolError("bad headers")),
            factory,
        )

        result = await check_monitor(ctx, monitor_id=monitor_id)

        assert result["is_success"] is False
        redis.enqueue_job.assert_called_once()
        args = redis.enqueue_job.call_args[0]
        assert args[0] == "send_alert_exception"
        assert args[6] == "request"

    # ------------------------------------------------------------------
    # SSL certificate expiry checks
    # ------------------------------------------------------------------

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_alert_queued_when_cert_expires_within_7_days(self, mock_ssl):
        mock_ssl.return_value = 5
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="https://example.com")
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_awaited_once_with("https://example.com")
        # Find the ssl alert enqueue call among all calls
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 1
        args = ssl_calls[0][0]
        assert args[6] == 5  # days_left

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_no_alert_when_cert_has_more_than_7_days(self, mock_ssl):
        mock_ssl.return_value = 30
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="https://example.com")
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_awaited_once()
        # No SSL alert should be enqueued
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 0

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_check_skipped_for_http_urls(self, mock_ssl):
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="http://example.com")
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_not_awaited()

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_check_runs_only_once_per_day(self, mock_ssl):
        """Second call within 24h should skip the SSL check (timer key exists)."""
        mock_ssl.return_value = 3
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="https://example.com")
                ).encode(),
                # Timer key already set — means we checked today
                f"monitor:{monitor_id}:ssl_checked_today": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_not_awaited()

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_alert_not_duplicated_within_24h(self, mock_ssl):
        """If ssl_alert_sent key exists, no second alert is queued."""
        mock_ssl.return_value = 2
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="https://example.com")
                ).encode(),
                # No ssl_checked_today — will run check
                # But alert already sent today
                f"monitor:{monitor_id}:ssl_alert_sent": b"1",
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_awaited_once()
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 0

    @patch("src.worker.monitoring.get_ssl_days_remaining", new_callable=AsyncMock)
    async def test_ssl_check_handles_none_gracefully(self, mock_ssl):
        """When get_ssl_days_remaining returns None (error/not HTTPS), no alert."""
        mock_ssl.return_value = None
        monitor_id = 1
        redis = _make_redis(
            {
                f"monitor:{monitor_id}:config": json.dumps(
                    _config(url="https://example.com")
                ).encode(),
            }
        )
        factory, _ = _make_session_factory()
        ctx = _ctx(redis, _http_client(200), factory)

        await check_monitor(ctx, monitor_id=monitor_id)

        mock_ssl.assert_awaited_once()
        ssl_calls = [
            c
            for c in redis.enqueue_job.call_args_list
            if c[0][0] == "send_alert_ssl_expiry"
        ]
        assert len(ssl_calls) == 0


# ---------------------------------------------------------------------------
# Tests: scheduler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScheduler:

    async def test_does_nothing_when_no_monitors_are_due(self):
        redis = _make_redis()
        redis.zrangebyscore = AsyncMock(return_value=[])
        factory, _ = _make_session_factory()
        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        redis.enqueue_job.assert_not_called()

    async def test_enqueues_check_job_for_each_due_monitor(self):
        redis = _make_redis(
            {
                "monitor:1:interval": b"60",
                "monitor:2:interval": b"120",
            }
        )
        redis.zrangebyscore = AsyncMock(return_value=["1", "2"])
        factory, _ = _make_session_factory()
        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        assert redis.enqueue_job.call_count == 2
        queued_ids = {c[0][1] for c in redis.enqueue_job.call_args_list}
        assert queued_ids == {1, 2}

    async def test_reschedules_monitor_using_redis_interval(self):
        redis = _make_redis({"monitor:7:interval": b"300"})
        redis.zrangebyscore = AsyncMock(return_value=["7"])
        factory, _ = _make_session_factory()
        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        redis.zadd.assert_called_once()
        payload = redis.zadd.call_args[0][1]
        assert "7" in payload
        assert payload["7"] > 0

    async def test_falls_back_to_db_when_interval_not_in_redis(self):
        from src.models.monitor import Monitor as MonitorModel

        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.is_active = True
        mock_monitor.interval = 60

        redis = _make_redis({})  # no interval key
        redis.zrangebyscore = AsyncMock(return_value=["5"])
        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = mock_monitor
        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        redis.enqueue_job.assert_called_once_with(
            "check_monitor", 5, _queue_name="arq:monitoring"
        )
        redis.zadd.assert_called_once()

    async def test_removes_zombie_task_when_monitor_not_in_db(self):
        redis = _make_redis({})
        redis.zrangebyscore = AsyncMock(return_value=["777"])
        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = None

        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        redis.zrem.assert_called_once_with("scheduler", "777")
        redis.zadd.assert_not_called()

    async def test_removes_paused_monitor_from_scheduler(self):
        from src.models.monitor import Monitor as MonitorModel

        mock_monitor = MagicMock(spec=MonitorModel)
        mock_monitor.is_active = False

        redis = _make_redis({})
        redis.zrangebyscore = AsyncMock(return_value=["42"])
        factory, mock_session = _make_session_factory()
        mock_session.get.return_value = mock_monitor
        ctx = {"redis": redis, "session_factory": factory}

        await scheduler(ctx)

        # The current-cycle job was already dispatched (job is enqueued before
        # interval/DB lookup); the monitor must be removed from future scheduling.
        redis.enqueue_job.assert_called_once_with(
            "check_monitor", 42, _queue_name="arq:monitoring"
        )
        redis.zrem.assert_called_once_with("scheduler", "42")
