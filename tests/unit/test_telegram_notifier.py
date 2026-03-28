from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.telegram.notifier import (
    AlertType,
    TelegramNotifier,
    get_http_error_description,
    get_predefined_message,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def notifier(mock_http_client: AsyncMock) -> Generator[TelegramNotifier, None, None]:
    with patch("src.telegram.notifier.settings") as mock_settings:
        mock_settings.telegram.token = "test-bot-token"
        yield TelegramNotifier(http_client=mock_http_client)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Tests: TelegramNotifier.send_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTelegramNotifier:

    async def test_returns_true_on_200_response(
        self, notifier: TelegramNotifier, mock_http_client: AsyncMock
    ):
        mock_http_client.post = AsyncMock(return_value=_mock_response(200))

        result = await notifier.send_message(chat_id=12345, text="Hello!")

        assert result is True
        mock_http_client.post.assert_called_once()

    async def test_sends_correct_payload(
        self, notifier: TelegramNotifier, mock_http_client: AsyncMock
    ):
        mock_http_client.post = AsyncMock(return_value=_mock_response(200))

        await notifier.send_message(chat_id=99, text="Test message")

        _, kwargs = mock_http_client.post.call_args
        payload = kwargs["json"]
        assert payload["chat_id"] == 99
        assert payload["text"] == "Test message"
        assert payload["parse_mode"] == "HTML"
        assert payload["disable_web_page_preview"] is True

    async def test_returns_false_on_non_200_response(
        self, notifier: TelegramNotifier, mock_http_client: AsyncMock
    ):
        mock_http_client.post = AsyncMock(return_value=_mock_response(429))

        result = await notifier.send_message(chat_id=12345, text="Hello!")

        assert result is False

    async def test_returns_false_on_exception(
        self, notifier: TelegramNotifier, mock_http_client: AsyncMock
    ):
        mock_http_client.post = AsyncMock(side_effect=httpx.RequestError("timeout"))

        result = await notifier.send_message(chat_id=12345, text="Hello!")

        assert result is False

    async def test_creates_own_http_client_when_none_injected(self):
        with patch("src.telegram.notifier.settings") as mock_settings:
            mock_settings.telegram.token = "test-token"
            notifier = TelegramNotifier(http_client=None)

        assert notifier._own_client is False
        assert notifier._http_client is None

        client = await notifier._get_client()

        assert client is not None
        assert notifier._own_client is True
        await notifier.close()


# ---------------------------------------------------------------------------
# Tests: get_predefined_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPredefinedMessage:

    def test_http_error_contains_status_code_and_url(self):
        msg = get_predefined_message(
            alert_type=AlertType.HTTP_ERROR,
            monitor_name="API",
            url="https://api.example.com",
            status_code=503,
        )

        assert "503" in msg
        assert "https://api.example.com" in msg
        assert "API" in msg

    def test_http_error_uses_status_description(self):
        msg = get_predefined_message(
            alert_type=AlertType.HTTP_ERROR,
            monitor_name="Shop",
            url="https://shop.example.com",
            status_code=404,
        )

        assert "Not Found" in msg

    def test_http_error_includes_duration_when_provided(self):
        msg = get_predefined_message(
            alert_type=AlertType.HTTP_ERROR,
            monitor_name="Service",
            url="https://service.example.com",
            status_code=500,
            duration_ms=1234,
        )

        assert "1234" in msg

    def test_recovery_contains_monitor_name_and_url(self):
        msg = get_predefined_message(
            alert_type=AlertType.RECOVERY,
            monitor_name="Main Site",
            url="https://main-site.example.com",
        )

        assert "Main Site" in msg
        assert "https://main-site.example.com" in msg
        assert "Recovered" in msg or "back online" in msg.lower()

    def test_timeout_message_contains_url_and_keyword(self):
        msg = get_predefined_message(
            alert_type=AlertType.TIMEOUT,
            monitor_name="Dashboard",
            url="https://dashboard.example.com",
        )

        assert "https://dashboard.example.com" in msg
        assert "Timeout" in msg or "timeout" in msg.lower()

    def test_connection_error_message_mentions_connection(self):
        msg = get_predefined_message(
            alert_type=AlertType.CONNECTION_ERROR,
            monitor_name="Backend",
            url="https://backend.example.com",
        )

        assert "Connection" in msg or "connection" in msg.lower()

    def test_request_error_includes_error_text(self):
        msg = get_predefined_message(
            alert_type=AlertType.REQUEST_ERROR,
            monitor_name="Worker",
            url="https://worker.example.com",
            error="SSL certificate expired",
        )

        assert "SSL certificate expired" in msg

    def test_uses_noname_when_monitor_name_is_empty(self):
        msg = get_predefined_message(
            alert_type=AlertType.RECOVERY,
            monitor_name="",
            url="https://example.com",
        )

        assert "Noname" in msg


# ---------------------------------------------------------------------------
# Tests: get_http_error_description
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetHttpErrorDescription:

    def test_returns_description_for_known_code(self):
        assert get_http_error_description(404) == "Not Found"
        assert get_http_error_description(500) == "Internal Server Error"
        assert get_http_error_description(403) == "Forbidden"

    def test_returns_generic_string_for_unknown_code(self):
        result = get_http_error_description(599)

        assert "599" in result

    def test_returns_unknown_error_for_none_code(self):
        result = get_http_error_description(0)

        assert result == "Unknown Error"
