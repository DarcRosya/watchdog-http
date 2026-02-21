import datetime
from unittest.mock import patch

import pytest

from src.utils.random_generate import generate_api_key, generate_random_username
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
