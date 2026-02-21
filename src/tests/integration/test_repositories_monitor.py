import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitor import Monitor
from src.models.user import User
from src.repositories.monitor import MonitorRepository


@pytest.mark.repository
@pytest.mark.integration
class TestMonitorRepository:

    async def test_create_persists_monitor_with_correct_fields(
        self, db_session: AsyncSession, sample_user: User
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        monitor_data = Monitor(
            user_id=sample_user.id,
            name="Test Monitor",
            url="https://example.com",
            method="GET",
            interval=60,
            is_active=True,
        )

        # Act
        created = await repo.create(monitor_data)

        # Assert
        assert created.id is not None
        assert created.user_id == sample_user.id
        assert created.name == "Test Monitor"
        assert created.url == "https://example.com"
        assert created.method == "GET"
        assert created.interval == 60
        assert created.is_active is True

    async def test_get_by_id_returns_monitor_when_it_exists(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        monitor = await create_monitor(user_id=sample_user.id, url="https://test.com")

        # Act
        found = await repo.get_by_id(monitor.id, sample_user.id)

        # Assert
        assert found is not None
        assert found.id == monitor.id

    async def test_get_by_id_returns_none_for_nonexistent_id(
        self, db_session: AsyncSession, sample_user: User
    ):
        # Arrange
        repo = MonitorRepository(db_session)

        # Act
        result = await repo.get_by_id(99999, sample_user.id)

        # Assert
        assert result is None

    async def test_get_all_by_user_returns_only_that_users_monitors(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        m1 = await create_monitor(user_id=sample_user.id, url="https://test1.com")
        m2 = await create_monitor(user_id=sample_user.id, url="https://test2.com")
        m3 = await create_monitor(user_id=sample_user.id, url="https://test3.com")

        # Act
        all_monitors = await repo.get_all_by_user(sample_user.id)

        # Assert
        assert len(all_monitors) == 3
        returned_ids = {m.id for m in all_monitors}
        assert {m1.id, m2.id, m3.id} == returned_ids

    async def test_get_active_by_user_excludes_inactive_monitors(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        active1 = await create_monitor(
            user_id=sample_user.id, url="https://active1.com", is_active=True
        )
        await create_monitor(
            user_id=sample_user.id, url="https://inactive1.com", is_active=False
        )
        active2 = await create_monitor(
            user_id=sample_user.id, url="https://active2.com", is_active=True
        )

        # Act
        active_monitors = await repo.get_active_by_user(sample_user.id)

        # Assert
        assert len(active_monitors) == 2
        active_ids = {m.id for m in active_monitors}
        assert active1.id in active_ids
        assert active2.id in active_ids
        assert all(m.is_active for m in active_monitors)

    async def test_bulk_create_persists_all_monitors(
        self, db_session: AsyncSession, sample_user: User
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        monitors_data = [
            Monitor(
                user_id=sample_user.id,
                name=f"Monitor {i}",
                url=f"https://example{i}.com",
                interval=60,
            )
            for i in range(5)
        ]

        # Act
        created = await repo.bulk_create(monitors_data)

        # Assert
        assert len(created) == 5
        assert all(m.id is not None for m in created)
        assert [m.name for m in created] == [f"Monitor {i}" for i in range(5)]

    async def test_update_fields_persists_changes(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        monitor = await create_monitor(
            user_id=sample_user.id, name="Old Name", url="https://old.com", interval=60
        )
        monitor.name = "New Name"
        monitor.interval = 120

        # Act
        updated = await repo.update_fields(monitor)

        # Assert
        assert updated.name == "New Name"
        assert updated.interval == 120
        refetched = await repo.get_by_id(monitor.id, sample_user.id)
        assert refetched is not None
        assert refetched.name == "New Name"
        assert refetched.interval == 120

    async def test_activate_all_sets_all_monitors_active(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        await create_monitor(user_id=sample_user.id, is_active=False)
        await create_monitor(user_id=sample_user.id, is_active=False)
        await create_monitor(user_id=sample_user.id, is_active=False)

        # Act
        count = await repo.activate_all(sample_user.id)

        # Assert
        assert count == 3
        active = await repo.get_active_by_user(sample_user.id)
        assert len(active) == 3

    async def test_deactivate_all_sets_all_monitors_inactive(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        await create_monitor(user_id=sample_user.id, is_active=True)
        await create_monitor(user_id=sample_user.id, is_active=True)

        # Act
        count = await repo.deactivate_all(sample_user.id)

        # Assert
        assert count == 2
        active = await repo.get_active_by_user(sample_user.id)
        assert len(active) == 0

    async def test_delete_removes_monitor_from_database(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        monitor = await create_monitor(user_id=sample_user.id)
        monitor_id = monitor.id

        # Act
        await repo.delete(monitor)

        # Assert
        deleted = await repo.get_by_id(monitor_id, sample_user.id)
        assert deleted is None

    async def test_monitors_are_isolated_between_users(
        self, db_session: AsyncSession, create_user, create_monitor
    ):
        # Arrange
        repo = MonitorRepository(db_session)
        user1 = await create_user(username="repo_iso_user1")
        user2 = await create_user(username="repo_iso_user2")
        await create_monitor(user_id=user1.id, url="https://user1a.com")
        await create_monitor(user_id=user1.id, url="https://user1b.com")
        await create_monitor(user_id=user2.id, url="https://user2a.com")

        # Act
        user1_monitors = await repo.get_all_by_user(user1.id)
        user2_monitors = await repo.get_all_by_user(user2.id)

        # Assert
        assert len(user1_monitors) == 2
        assert len(user2_monitors) == 1
        assert all(m.user_id == user1.id for m in user1_monitors)
        assert all(m.user_id == user2.id for m in user2_monitors)
