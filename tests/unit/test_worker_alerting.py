from unittest.mock import AsyncMock

import pytest

from src.worker.alerting import (
    send_alert_exception,
    send_alert_http_error,
    send_alert_recovery,
    send_alert_ssl_expiry,
    send_telegram_message,
)

# ---------------------------------------------------------------------------
# Tests: send_telegram_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendTelegramMessage:

    async def test_returns_sent_when_notifier_succeeds(self):
        notifier = AsyncMock()
        notifier.send_message = AsyncMock(return_value=True)
        ctx = {"notifier": notifier}

        result = await send_telegram_message(
            ctx, chat_id=12345, message="hello", alert_metadata={"alert_type": "test"}
        )

        assert result["status"] == "sent"
        notifier.send_message.assert_called_once_with(12345, "hello")

    async def test_returns_failed_when_notifier_returns_false(self):
        notifier = AsyncMock()
        notifier.send_message = AsyncMock(return_value=False)
        ctx = {"notifier": notifier}

        result = await send_telegram_message(
            ctx, chat_id=12345, message="hello", alert_metadata={}
        )

        assert result["status"] == "failed"

    async def test_includes_alert_metadata_in_response(self):
        notifier = AsyncMock()
        notifier.send_message = AsyncMock(return_value=True)
        ctx = {"notifier": notifier}
        metadata = {"alert_type": "http_error", "monitor_id": 7}

        result = await send_telegram_message(
            ctx, chat_id=1, message="msg", alert_metadata=metadata
        )

        assert result["alert_type"] == "http_error"
        assert result["monitor_id"] == 7


# ---------------------------------------------------------------------------
# Tests: send_alert_http_error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendAlertHttpError:

    async def test_queues_telegram_message_and_returns_queued(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_http_error(
            ctx,
            chat_id=99,
            username="alice",
            monitor_id=1,
            monitor_name="My API",
            monitor_url="https://api.example.com",
            status_code=500,
            duration_ms=350,
        )

        assert result["status"] == "queued"
        assert result["monitor_id"] == 1
        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_telegram_message"

    async def test_message_contains_status_code_description(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        await send_alert_http_error(
            ctx,
            chat_id=99,
            username="alice",
            monitor_id=1,
            monitor_name="Shop",
            monitor_url="https://shop.example.com",
            status_code=404,
            duration_ms=100,
        )

        message = redis.enqueue_job.call_args[0][2]
        assert "404" in message or "Not Found" in message

    async def test_skips_when_chat_id_is_none(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_http_error(
            ctx,
            chat_id=None,
            username="alice",
            monitor_id=1,
            monitor_name="Monitor",
            monitor_url="https://example.com",
            status_code=500,
            duration_ms=200,
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_telegram"
        redis.enqueue_job.assert_not_called()

    async def test_skips_when_chat_id_is_zero(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_http_error(
            ctx,
            chat_id=0,
            username="bob",
            monitor_id=2,
            monitor_name="Monitor",
            monitor_url="https://example.com",
            status_code=503,
            duration_ms=100,
        )

        assert result["status"] == "skipped"
        redis.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: send_alert_exception
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendAlertException:

    async def test_queues_alert_for_timeout_type(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_exception(
            ctx,
            chat_id=42,
            username="bob",
            monitor_id=3,
            monitor_name="Service",
            monitor_url="https://service.example.com",
            alert_type="timeout",
        )

        assert result["status"] == "queued"
        assert result["alert_type"] == "timeout"
        redis.enqueue_job.assert_called_once()
        message = redis.enqueue_job.call_args[0][2]
        assert "Timeout" in message or "timeout" in message.lower()

    async def test_queues_alert_for_connection_type(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_exception(
            ctx,
            chat_id=42,
            username="bob",
            monitor_id=3,
            monitor_name="Service",
            monitor_url="https://service.example.com",
            alert_type="connection",
        )

        assert result["status"] == "queued"
        message = redis.enqueue_job.call_args[0][2]
        assert "Connection" in message or "connection" in message.lower()

    async def test_queues_alert_for_request_type_with_error_message(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_exception(
            ctx,
            chat_id=42,
            username="bob",
            monitor_id=3,
            monitor_name="Service",
            monitor_url="https://service.example.com",
            alert_type="request",
            error_message="SSL handshake failed",
        )

        assert result["status"] == "queued"
        message = redis.enqueue_job.call_args[0][2]
        assert "SSL handshake failed" in message

    async def test_skips_when_no_telegram_configured(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_exception(
            ctx,
            chat_id=None,
            username="bob",
            monitor_id=3,
            monitor_name="Service",
            monitor_url="https://service.example.com",
            alert_type="timeout",
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_telegram"
        redis.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: send_alert_recovery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendAlertRecovery:

    async def test_queues_recovery_message(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_recovery(
            ctx,
            chat_id=55,
            username="carol",
            monitor_id=10,
            monitor_name="Main Site",
            monitor_url="https://main-site.example.com",
        )

        assert result["status"] == "queued"
        assert result["monitor_id"] == 10
        redis.enqueue_job.assert_called_once()
        message = redis.enqueue_job.call_args[0][2]
        assert "Recovered" in message or "back online" in message.lower()

    async def test_recovery_message_contains_monitor_name_and_url(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        await send_alert_recovery(
            ctx,
            chat_id=55,
            username="carol",
            monitor_id=10,
            monitor_name="My Store",
            monitor_url="https://my-store.com",
        )

        message = redis.enqueue_job.call_args[0][2]
        assert "My Store" in message
        assert "https://my-store.com" in message

    async def test_skips_when_no_telegram_configured(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_recovery(
            ctx,
            chat_id=None,
            username="carol",
            monitor_id=10,
            monitor_name="Monitor",
            monitor_url="https://example.com",
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_telegram"
        redis.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: send_alert_ssl_expiry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendAlertSslExpiry:

    async def test_queues_ssl_expiry_message(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_ssl_expiry(
            ctx,
            chat_id=55,
            username="dave",
            monitor_id=7,
            monitor_name="Secure API",
            monitor_url="https://secure-api.example.com",
            days_left=5,
        )

        assert result["status"] == "queued"
        assert result["monitor_id"] == 7
        assert result["days_left"] == 5
        redis.enqueue_job.assert_called_once()
        assert redis.enqueue_job.call_args[0][0] == "send_telegram_message"

    async def test_message_contains_days_left_and_url(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        await send_alert_ssl_expiry(
            ctx,
            chat_id=55,
            username="dave",
            monitor_id=7,
            monitor_name="My Site",
            monitor_url="https://my-site.com",
            days_left=3,
        )

        message = redis.enqueue_job.call_args[0][2]
        assert "3" in message
        assert "https://my-site.com" in message
        assert "SSL" in message or "certificate" in message.lower()

    async def test_skips_when_no_telegram_configured(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_ssl_expiry(
            ctx,
            chat_id=None,
            username="dave",
            monitor_id=7,
            monitor_name="Secure API",
            monitor_url="https://example.com",
            days_left=2,
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_telegram"
        redis.enqueue_job.assert_not_called()

    async def test_skips_when_chat_id_is_zero(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        result = await send_alert_ssl_expiry(
            ctx,
            chat_id=0,
            username="dave",
            monitor_id=7,
            monitor_name="Site",
            monitor_url="https://example.com",
            days_left=1,
        )

        assert result["status"] == "skipped"
        redis.enqueue_job.assert_not_called()

    async def test_message_contains_monitor_name(self):
        redis = AsyncMock()
        ctx = {"redis": redis}

        await send_alert_ssl_expiry(
            ctx,
            chat_id=55,
            username="dave",
            monitor_id=7,
            monitor_name="Production Gateway",
            monitor_url="https://gw.example.com",
            days_left=1,
        )

        message = redis.enqueue_job.call_args[0][2]
        assert "Production Gateway" in message
