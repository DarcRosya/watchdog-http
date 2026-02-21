from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import Response

from src.schemas.monitor import MonitorCreate
from src.services.monitor import MonitorService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor(**kwargs) -> MagicMock:
    """
    Return a plain MagicMock that looks like a Monitor.

    Using MagicMock instead of a real SQLAlchemy model avoids triggering
    the ORM's instance-state machinery (which is never initialised when you
    bypass __init__ via object.__new__).
    """
    defaults = dict(
        id=1,
        user_id=1,
        name="Test",
        url="https://example.com",
        interval=60,
        is_active=True,
    )
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMonitorServiceUnit:

    # --- get_all_by_user ---------------------------------------------------

    @patch("src.services.monitor.MonitorRepository")
    async def test_get_all_by_user_returns_list(self, MockRepo):
        # Arrange
        expected = [_make_monitor(id=1), _make_monitor(id=2)]
        mock_repo = AsyncMock()
        mock_repo.get_all_by_user.return_value = expected
        MockRepo.return_value = mock_repo
        service = MonitorService(session=AsyncMock())

        # Act
        result = await service.get_all_by_user(user_id=42)

        # Assert
        assert result == expected
        mock_repo.get_all_by_user.assert_called_once_with(42)

    @patch("src.services.monitor.MonitorRepository")
    async def test_get_all_by_user_returns_empty_list_when_no_monitors(self, MockRepo):
        # Arrange
        mock_repo = AsyncMock()
        mock_repo.get_all_by_user.return_value = []
        MockRepo.return_value = mock_repo
        service = MonitorService(session=AsyncMock())

        # Act
        result = await service.get_all_by_user(user_id=42)

        # Assert
        assert result == []

    # --- get_by_id ---------------------------------------------------------

    @patch("src.services.monitor.MonitorRepository")
    async def test_get_by_id_returns_monitor_when_found(self, MockRepo):
        # Arrange
        expected = _make_monitor(id=5, user_id=42)
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = expected
        MockRepo.return_value = mock_repo
        service = MonitorService(session=AsyncMock())

        # Act
        result = await service.get_by_id(monitor_id=5, user_id=42)

        # Assert
        assert result is expected
        mock_repo.get_by_id.assert_called_once_with(5, 42)

    @patch("src.services.monitor.MonitorRepository")
    async def test_get_by_id_returns_none_when_not_found(self, MockRepo):
        # Arrange
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        MockRepo.return_value = mock_repo
        service = MonitorService(session=AsyncMock())

        # Act
        result = await service.get_by_id(monitor_id=99999, user_id=42)

        # Assert
        assert result is None

    # --- bulk_create_monitors ----------------------------------------------

    @patch("src.services.monitor.MonitorRepository")
    @patch("src.services.monitor.httpx.AsyncClient")
    async def test_bulk_create_creates_all_monitors_when_urls_are_reachable(
        self, MockHttpx, MockRepo
    ):
        # Arrange
        mock_client = AsyncMock()
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        MockHttpx.return_value = mock_client

        created = [_make_monitor(id=1, name="M1"), _make_monitor(id=2, name="M2")]
        mock_repo = AsyncMock()
        mock_repo.bulk_create.return_value = created
        MockRepo.return_value = mock_repo

        service = MonitorService(session=AsyncMock(), redis=None)
        monitors_data = [
            MonitorCreate(
                url="https://example1.com", name="M1", interval=60, method="GET"
            ),
            MonitorCreate(
                url="https://example2.com", name="M2", interval=60, method="GET"
            ),
        ]

        # Act
        result = await service.bulk_create_monitors(monitors_data, user_id=1)

        # Assert
        assert result == created
        mock_repo.bulk_create.assert_called_once()
        assert len(mock_repo.bulk_create.call_args[0][0]) == 2

    @patch("src.services.monitor.MonitorRepository")
    @patch("src.services.monitor.httpx.AsyncClient")
    async def test_bulk_create_still_creates_monitor_when_url_unreachable(
        self, MockHttpx, MockRepo
    ):
        """An unreachable URL is a warning, not a blocker – the monitor must still be created."""
        # Arrange
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        MockHttpx.return_value = mock_client

        created = [_make_monitor(id=1, url="https://unavailable.com")]
        mock_repo = AsyncMock()
        mock_repo.bulk_create.return_value = created
        MockRepo.return_value = mock_repo

        service = MonitorService(session=AsyncMock(), redis=None)
        monitors_data = [
            MonitorCreate(
                url="https://unavailable.com",
                name="Unavailable",
                interval=60,
                method="GET",
            ),
        ]

        # Act
        result = await service.bulk_create_monitors(monitors_data, user_id=1)

        # Assert
        assert len(result) == 1
        mock_repo.bulk_create.assert_called_once()

    @patch("src.services.monitor.MonitorRepository")
    @patch("src.services.monitor.httpx.AsyncClient")
    async def test_bulk_create_does_not_call_redis_when_redis_is_none(
        self, MockHttpx, MockRepo
    ):
        # Arrange
        mock_client = AsyncMock()
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        MockHttpx.return_value = mock_client

        created = [_make_monitor(id=1)]
        mock_repo = AsyncMock()
        mock_repo.bulk_create.return_value = created
        MockRepo.return_value = mock_repo

        mock_redis = AsyncMock()
        service = MonitorService(session=AsyncMock(), redis=None)
        monitors_data = [
            MonitorCreate(
                url="https://example.com", name="M", interval=60, method="GET"
            ),
        ]

        # Act
        result = await service.bulk_create_monitors(monitors_data, user_id=1)

        # Assert
        assert result == created
        mock_redis.zadd.assert_not_called()
