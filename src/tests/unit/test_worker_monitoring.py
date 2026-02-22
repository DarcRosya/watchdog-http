import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import Response

from src.worker.monitoring import check_monitor
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

    redis.get = AsyncMock(side_effect=_get)
    redis.setex = AsyncMock(side_effect=_setex)
    redis.set = AsyncMock(side_effect=_set_cmd)
    redis.delete = AsyncMock(side_effect=_delete)
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


# ---------------------------------------------------------------------------
# Tests: check_monitor
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
