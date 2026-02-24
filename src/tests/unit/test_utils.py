import datetime
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from src.utils.random_generate import generate_api_key, generate_random_username
from src.utils.ssl_checker import get_ssl_days_remaining
from src.utils.time import get_next_aligned_time


@pytest.mark.unit
class TestRandomGenerateUtils:

    def test_generate_api_key_returns_64_chars(self):
        key = generate_api_key()

        assert isinstance(key, str)
        assert len(key) == 64

    def test_generate_api_key_is_unique(self):
        key1 = generate_api_key()
        key2 = generate_api_key()

        assert key1 != key2

    def test_generate_random_username_returns_string(self):
        username = generate_random_username()

        assert isinstance(username, str)
        assert len(username) > 0
        assert "-" in username

    def test_generate_random_username_is_unique(self):
        """Checking the entropy of the name generator."""
        name1 = generate_random_username()
        name2 = generate_random_username()

        # The probability of a 2-word combination occurring tends toward zero.
        assert name1 != name2


@pytest.mark.unit
class TestTimeUtils:

    @patch("src.utils.time.datetime")
    def test_get_next_aligned_time_with_60_seconds(self, mock_datetime):
        # Arrange: Freeze time at 14:23:47.123456
        frozen_time = datetime.datetime(
            2026, 2, 21, 14, 23, 47, 123456, tzinfo=datetime.timezone.utc
        )
        mock_datetime.now.return_value = frozen_time

        # Act
        result = get_next_aligned_time(interval_seconds=60)

        # Assert: We expect exactly 14:24:00.000000
        expected_time = datetime.datetime(
            2026, 2, 21, 14, 24, 0, tzinfo=datetime.timezone.utc
        )
        assert result == expected_time
        assert result.microsecond == 0
        assert result.second == 0

    @patch("src.utils.time.datetime")
    def test_get_next_aligned_time_handles_hour_rollover(self, mock_datetime):
        """Edge case (Boundary case): transition after one hour."""
        # Freeze at 14:59:59
        frozen_time = datetime.datetime(
            2026, 2, 21, 14, 59, 59, tzinfo=datetime.timezone.utc
        )
        mock_datetime.now.return_value = frozen_time

        # Act
        result = get_next_aligned_time(interval_seconds=60)

        # Assert: Should be 15:00:00
        expected_time = datetime.datetime(
            2026, 2, 21, 15, 0, 0, tzinfo=datetime.timezone.utc
        )
        assert result == expected_time
        assert result.hour == 15
        assert result.minute == 0

    @patch("src.utils.time.datetime")
    def test_get_next_aligned_time_with_custom_interval(self, mock_datetime):
        """
        Logic check with custom interval (shows current behavior).
        If you set an interval of 300 seconds (5 minutes) at 14:23:47, it will be 14:28:00.
        """
        frozen_time = datetime.datetime(
            2026, 2, 21, 14, 23, 47, tzinfo=datetime.timezone.utc
        )
        mock_datetime.now.return_value = frozen_time

        result = get_next_aligned_time(interval_seconds=300)

        expected_time = datetime.datetime(
            2026, 2, 21, 14, 28, 0, tzinfo=datetime.timezone.utc
        )
        assert result == expected_time


@pytest.mark.unit
class TestSslChecker:

    async def test_returns_none_for_http_url(self):
        result = await get_ssl_days_remaining("http://example.com")

        assert result is None

    async def test_returns_none_for_url_without_scheme(self):
        result = await get_ssl_days_remaining("ftp://example.com")

        assert result is None

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_returns_days_remaining_for_valid_cert(self, mock_wait_for):
        # Simulate a certificate expiring in 30 days
        expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            days=30
        )
        expire_str = expire_date.strftime("%b %d %H:%M:%S %Y GMT")

        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = {"notAfter": expire_str}
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_reader = MagicMock()
        mock_wait_for.return_value = (mock_reader, mock_writer)

        result = await get_ssl_days_remaining("https://example.com")

        assert result is not None
        assert 29 <= result <= 30

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_returns_negative_days_for_expired_cert(self, mock_wait_for):
        expire_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=5
        )
        expire_str = expire_date.strftime("%b %d %H:%M:%S %Y GMT")

        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = {"notAfter": expire_str}
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_reader = MagicMock()
        mock_wait_for.return_value = (mock_reader, mock_writer)

        result = await get_ssl_days_remaining("https://expired.example.com")

        assert result is not None
        assert result < 0

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_returns_none_when_cert_has_no_notafter(self, mock_wait_for):
        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = {}  # No notAfter
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_reader = MagicMock()
        mock_wait_for.return_value = (mock_reader, mock_writer)

        result = await get_ssl_days_remaining("https://example.com")

        assert result is None

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_returns_none_when_connection_fails(self, mock_wait_for):
        mock_wait_for.side_effect = ConnectionRefusedError("refused")

        result = await get_ssl_days_remaining("https://down.example.com")

        assert result is None

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_returns_none_on_timeout(self, mock_wait_for):
        import asyncio

        mock_wait_for.side_effect = asyncio.TimeoutError()

        result = await get_ssl_days_remaining("https://slow.example.com")

        assert result is None

    @patch("src.utils.ssl_checker.asyncio.wait_for", new_callable=AsyncMock)
    async def test_uses_custom_port_from_url(self, mock_wait_for):
        expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            days=15
        )
        expire_str = expire_date.strftime("%b %d %H:%M:%S %Y GMT")

        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = {"notAfter": expire_str}
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        mock_reader = MagicMock()
        mock_wait_for.return_value = (mock_reader, mock_writer)

        result = await get_ssl_days_remaining("https://example.com:8443/path")

        assert result is not None
        assert 14 <= result <= 15
        mock_wait_for.assert_awaited_once()
