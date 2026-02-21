from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.resultlog import ResultLog
from src.models.user import User
from src.repositories.resultlog import ResultLogRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _create_log(
    session: AsyncSession,
    *,
    monitor_id: int,
    start_time: datetime,
    duration_ms: int = 120,
    status_code: int | None = 200,
    is_success: bool = True,
    error_message: str | None = None,
) -> ResultLog:
    log = ResultLog(
        monitor_id=monitor_id,
        start_time=start_time,
        duration_ms=duration_ms,
        status_code=status_code,
        is_success=is_success,
        error_message=error_message,
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)
    return log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.repository
@pytest.mark.integration
class TestResultLogRepository:

    # --- create ------------------------------------------------------------

    async def test_create_persists_log_with_correct_fields(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        repo = ResultLogRepository(db_session)
        now = _utcnow()
        log = ResultLog(
            monitor_id=monitor.id,
            start_time=now,
            duration_ms=250,
            status_code=200,
            is_success=True,
        )

        # Act
        created = await repo.create(log)

        # Assert
        assert created.monitor_id == monitor.id
        assert created.is_success is True
        assert created.status_code == 200
        assert created.duration_ms == 250
        assert created.error_message is None

    async def test_create_persists_failed_log_with_error_message(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        repo = ResultLogRepository(db_session)
        log = ResultLog(
            monitor_id=monitor.id,
            start_time=_utcnow(),
            duration_ms=5000,
            status_code=None,
            is_success=False,
            error_message="Connection timed out",
        )

        # Act
        created = await repo.create(log)

        # Assert
        assert created.is_success is False
        assert created.status_code is None
        assert created.error_message == "Connection timed out"

    # --- get_by_monitor ----------------------------------------------------

    async def test_get_by_monitor_returns_logs_within_time_range(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        for delta_minutes in [5, 10, 15]:
            await _create_log(
                db_session,
                monitor_id=monitor.id,
                start_time=now - timedelta(minutes=delta_minutes),
            )

        # Act
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(minutes=20),
            end_time=now,
        )

        # Assert
        assert total == 3
        assert len(logs) == 3

    async def test_get_by_monitor_excludes_logs_outside_time_range(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        await _create_log(
            db_session, monitor_id=monitor.id, start_time=now - timedelta(hours=2)
        )
        await _create_log(
            db_session, monitor_id=monitor.id, start_time=now - timedelta(minutes=10)
        )

        # Act – query only the last 30 minutes
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(minutes=30),
            end_time=now,
        )

        # Assert – the 2-hour-old log must be excluded
        assert total == 1
        assert len(logs) == 1

    async def test_get_by_monitor_returns_empty_when_no_logs_exist(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        # Act
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(hours=1),
            end_time=now,
        )

        # Assert
        assert total == 0
        assert logs == []

    async def test_get_by_monitor_respects_limit(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        for i in range(5):
            await _create_log(
                db_session,
                monitor_id=monitor.id,
                start_time=now - timedelta(minutes=i + 1),
            )

        # Act
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(hours=1),
            end_time=now,
            limit=2,
        )

        # Assert – total reflects all records; logs is capped by limit
        assert total == 5
        assert len(logs) == 2

    async def test_get_by_monitor_respects_offset(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        for i in range(4):
            await _create_log(
                db_session,
                monitor_id=monitor.id,
                start_time=now - timedelta(minutes=i + 1),
            )

        # Act – skip 2, take the rest
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(hours=1),
            end_time=now,
            offset=2,
        )

        # Assert
        assert total == 4
        assert len(logs) == 2

    async def test_get_by_monitor_returns_logs_ordered_by_start_time_desc(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        oldest = now - timedelta(minutes=30)
        middle = now - timedelta(minutes=15)
        newest = now - timedelta(minutes=5)

        for t in [oldest, middle, newest]:
            await _create_log(db_session, monitor_id=monitor.id, start_time=t)

        # Act
        logs, _ = await repo.get_by_monitor(
            monitor_id=monitor.id,
            start_time=now - timedelta(hours=1),
            end_time=now,
        )

        # Assert – most recent first
        assert logs[0].start_time > logs[1].start_time > logs[2].start_time

    async def test_get_by_monitor_does_not_return_other_monitors_logs(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor_a = await create_monitor(user_id=sample_user.id)
        monitor_b = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        await _create_log(
            db_session, monitor_id=monitor_a.id, start_time=now - timedelta(minutes=5)
        )
        await _create_log(
            db_session, monitor_id=monitor_b.id, start_time=now - timedelta(minutes=5)
        )

        # Act
        logs, total = await repo.get_by_monitor(
            monitor_id=monitor_a.id,
            start_time=now - timedelta(hours=1),
            end_time=now,
        )

        # Assert
        assert total == 1
        assert logs[0].monitor_id == monitor_a.id

    # --- get_latest_by_monitor ---------------------------------------------

    async def test_get_latest_by_monitor_returns_most_recent_log(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        await _create_log(
            db_session, monitor_id=monitor.id, start_time=now - timedelta(minutes=20)
        )
        await _create_log(
            db_session, monitor_id=monitor.id, start_time=now - timedelta(minutes=10)
        )
        latest_time = now - timedelta(minutes=1)
        await _create_log(db_session, monitor_id=monitor.id, start_time=latest_time)

        # Act
        result = await repo.get_latest_by_monitor(monitor.id)

        # Assert
        assert result is not None
        assert result.start_time == latest_time

    async def test_get_latest_by_monitor_returns_none_when_no_logs(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor = await create_monitor(user_id=sample_user.id)
        repo = ResultLogRepository(db_session)

        # Act
        result = await repo.get_latest_by_monitor(monitor.id)

        # Assert
        assert result is None

    async def test_get_latest_by_monitor_does_not_cross_monitor_boundary(
        self, db_session: AsyncSession, sample_user: User, create_monitor
    ):
        # Arrange
        monitor_a = await create_monitor(user_id=sample_user.id)
        monitor_b = await create_monitor(user_id=sample_user.id)
        now = _utcnow()
        repo = ResultLogRepository(db_session)

        # Only monitor_b has a log
        await _create_log(
            db_session, monitor_id=monitor_b.id, start_time=now - timedelta(minutes=5)
        )

        # Act
        result = await repo.get_latest_by_monitor(monitor_a.id)

        # Assert
        assert result is None
