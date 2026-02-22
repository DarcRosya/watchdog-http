import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import redis.asyncio as aioredis
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.schemas.monitor import MonitorCreate
from src.services.monitor import MonitorService


@pytest.mark.service
@pytest.mark.integration
class TestMonitorServiceIntegration:

    # --- DB delegation (smoke tests verifying repo wiring) -----------------

    async def test_get_all_by_user_returns_all_monitors(
        self,
        db_session: AsyncSession,
        sample_user: User,
        create_monitor,
    ):
        # Arrange
        await create_monitor(user_id=sample_user.id, url="https://svc-test1.com")
        await create_monitor(user_id=sample_user.id, url="https://svc-test2.com")
        await create_monitor(user_id=sample_user.id, url="https://svc-test3.com")
        service = MonitorService(db_session)

        # Act
        monitors = await service.get_all_by_user(sample_user.id)

        # Assert
        assert len(monitors) == 3
        assert all(m.user_id == sample_user.id for m in monitors)

    async def test_get_by_id_returns_correct_monitor(
        self,
        db_session: AsyncSession,
        sample_user: User,
        create_monitor,
    ):
        # Arrange
        target = await create_monitor(
            user_id=sample_user.id, url="https://svc-by-id.com"
        )
        service = MonitorService(db_session)

        # Act
        monitor = await service.get_by_id(target.id, sample_user.id)

        # Assert
        assert monitor is not None
        assert monitor.id == target.id
        assert monitor.url == target.url

    async def test_get_by_id_returns_none_for_nonexistent_monitor(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ):
        # Arrange
        service = MonitorService(db_session)

        # Act
        result = await service.get_by_id(monitor_id=99999, user_id=sample_user.id)

        # Assert
        assert result is None

    # --- Redis integration -------------------------------------------------

    @patch("src.services.monitor.httpx.AsyncClient")
    async def test_bulk_create_writes_monitor_config_to_redis(
        self,
        mock_client_class,
        db_session: AsyncSession,
        redis_client: aioredis.Redis,
        clean_redis,
        sample_user: User,
    ):
        # Arrange
        mock_client = AsyncMock()
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        service = MonitorService(db_session, redis_client)
        monitors_data = [
            MonitorCreate(
                url="https://bulk1.com",  # type: ignore[arg-type]
                name="Monitor 1",
                interval=60,
                method="GET",  # type: ignore[arg-type]
                headers=None,
                body=None,
            ),
            MonitorCreate(
                url="https://bulk2.com",  # type: ignore[arg-type]
                name="Monitor 2",
                interval=120,
                method="GET",  # type: ignore[arg-type]
                headers=None,
                body=None,
            ),
        ]

        # Act
        created = await service.bulk_create_monitors(monitors_data, sample_user.id)

        # Assert
        assert len(created) == 2
        for monitor in created:
            interval = await redis_client.get(f"monitor:{monitor.id}:interval")
            config_json = await redis_client.get(f"monitor:{monitor.id}:config")
            score = await redis_client.zscore("scheduler", str(monitor.id))

            assert interval is not None
            assert config_json is not None
            assert score is not None

            config = json.loads(config_json)
            assert config["url"] == monitor.url

    @patch("src.services.monitor.httpx.AsyncClient")
    async def test_bulk_create_still_creates_monitor_when_url_unreachable(
        self,
        mock_client_class,
        db_session: AsyncSession,
        sample_user: User,
    ):
        # Arrange
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("Connection refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        service = MonitorService(db_session)
        monitors_data = [
            MonitorCreate(
                url="https://unreachable.com",  # type: ignore[arg-type]
                name="Unavailable Monitor",
                interval=60,
                method="GET",  # type: ignore[arg-type]
                headers=None,
                body=None,
            ),
        ]

        # Act
        created = await service.bulk_create_monitors(monitors_data, sample_user.id)

        # Assert
        assert len(created) == 1
        assert created[0].url.rstrip("/") == "https://unreachable.com"

    async def test_add_monitors_to_redis_stores_interval_config_and_schedule(
        self,
        db_session: AsyncSession,
        redis_client: aioredis.Redis,
        clean_redis,
        sample_user: User,
        create_monitor,
    ):
        # Arrange
        service = MonitorService(db_session, redis_client)
        monitor = await create_monitor(
            user_id=sample_user.id,
            url="https://redis-test.com",
            name="Redis Test Monitor",
            interval=60,
            is_active=True,
        )

        # Act
        await service._add_monitors_to_redis([monitor])

        # Assert
        interval = await redis_client.get(f"monitor:{monitor.id}:interval")
        config_json = await redis_client.get(f"monitor:{monitor.id}:config")
        score = await redis_client.zscore("scheduler", str(monitor.id))

        assert int(interval) == 60
        assert config_json is not None
        config = json.loads(config_json)
        assert config["url"] == "https://redis-test.com"
        assert config["name"] == "Redis Test Monitor"
        assert config["user_id"] == sample_user.id
        assert score > 0

    async def test_remove_monitors_from_redis_deletes_all_keys(
        self,
        db_session: AsyncSession,
        redis_client: aioredis.Redis,
        clean_redis,
        sample_user: User,
        create_monitor,
    ):
        # Arrange
        service = MonitorService(db_session, redis_client)
        monitor = await create_monitor(
            user_id=sample_user.id,
            url="https://redis-remove.com",
            interval=60,
            is_active=True,
        )
        await service._add_monitors_to_redis([monitor])
        assert await redis_client.get(f"monitor:{monitor.id}:config") is not None

        # Act
        await service._remove_monitors_from_redis([monitor.id])

        # Assert
        assert await redis_client.get(f"monitor:{monitor.id}:interval") is None
        assert await redis_client.get(f"monitor:{monitor.id}:config") is None
        assert await redis_client.get(f"monitor:{monitor.id}:state") is None
        assert await redis_client.get(f"monitor:{monitor.id}:failures") is None
        assert await redis_client.zscore("scheduler", str(monitor.id)) is None

    async def test_service_works_correctly_without_redis(
        self,
        db_session: AsyncSession,
        sample_user: User,
        create_monitor,
    ):
        # Arrange
        service = MonitorService(db_session, redis=None)
        monitor = await create_monitor(user_id=sample_user.id)

        # Act
        monitors = await service.get_all_by_user(sample_user.id)

        # Assert
        assert len(monitors) > 0
        assert monitors[0].id == monitor.id
