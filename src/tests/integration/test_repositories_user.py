import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.repositories.user import UserRepository


@pytest.mark.repository
@pytest.mark.integration
class TestUserRepository:

    async def test_create_generates_id_and_api_key(self, db_session: AsyncSession):
        # Arrange
        repo = UserRepository(db_session)
        user_data = User(username="test_user", telegram_chat_id=123456789)

        # Act
        created = await repo.create(user_data)

        # Assert
        assert created.id is not None
        assert created.username == "test_user"
        assert created.api_key is not None
        assert len(created.api_key) == 64
        assert created.telegram_chat_id == 123456789
        assert created.created_at is not None

    async def test_get_by_id_returns_user_when_found(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        user = await create_user(username="find_me")

        # Act
        found = await repo.get_by_id(user.id)

        # Assert
        assert found is not None
        assert found.id == user.id
        assert found.username == "find_me"

    async def test_get_by_id_returns_none_for_nonexistent_id(
        self, db_session: AsyncSession
    ):
        # Arrange
        repo = UserRepository(db_session)

        # Act
        result = await repo.get_by_id(99999)

        # Assert
        assert result is None

    async def test_get_by_username_returns_correct_user(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        user = await create_user(username="unique_username")

        # Act
        found = await repo.get_by_username("unique_username")

        # Assert
        assert found is not None
        assert found.id == user.id

    async def test_get_by_username_returns_none_for_unknown_name(
        self, db_session: AsyncSession
    ):
        # Arrange
        repo = UserRepository(db_session)

        # Act
        result = await repo.get_by_username("nonexistent_user_xyz")

        # Assert
        assert result is None

    async def test_get_by_api_key_returns_correct_user(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        api_key = "test-api-key-123456789012345678901234567890123456789012345"
        user = await create_user(username="api_user", api_key=api_key)

        # Act
        found = await repo.get_by_api_key(api_key)

        # Assert
        assert found is not None
        assert found.id == user.id

    async def test_get_by_api_key_returns_none_for_unknown_key(
        self, db_session: AsyncSession
    ):
        # Arrange
        repo = UserRepository(db_session)

        # Act
        result = await repo.get_by_api_key("nonexistent-api-key-xyz")

        # Assert
        assert result is None

    async def test_get_by_telegram_id_returns_correct_user(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        user = await create_user(username="telegram_user", telegram_chat_id=987654321)

        # Act
        found = await repo.get_by_telegram_id(987654321)

        # Assert
        assert found is not None
        assert found.id == user.id

    async def test_get_by_telegram_id_returns_none_for_unknown_id(
        self, db_session: AsyncSession
    ):
        # Arrange
        repo = UserRepository(db_session)

        # Act
        result = await repo.get_by_telegram_id(11111111)

        # Assert
        assert result is None

    async def test_get_by_ids_returns_dict_of_matching_users(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        user1 = await create_user(username="bulk_user1")
        user2 = await create_user(username="bulk_user2")
        user3 = await create_user(username="bulk_user3")

        # Act
        result = await repo.get_by_ids([user1.id, user2.id, user3.id, 99999])

        # Assert
        assert len(result) == 3
        assert user1.id in result
        assert user2.id in result
        assert user3.id in result
        assert 99999 not in result
        assert result[user1.id].username == "bulk_user1"

    async def test_update_fields_persists_changes(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        repo = UserRepository(db_session)
        user = await create_user(username="old_name", telegram_chat_id=111111)
        user.username = "new_name"
        user.telegram_chat_id = 222222

        # Act
        updated = await repo.update_fields(user)

        # Assert
        assert updated.username == "new_name"
        assert updated.telegram_chat_id == 222222
        refetched = await repo.get_by_id(user.id)
        assert refetched is not None
        assert refetched.username == "new_name"
        assert refetched.telegram_chat_id == 222222

    async def test_api_keys_are_unique_across_users(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange
        user1 = await create_user(username="key_user1")
        user2 = await create_user(username="key_user2")
        user3 = await create_user(username="key_user3")

        # Act
        api_keys = {user1.api_key, user2.api_key, user3.api_key}

        # Assert
        assert len(api_keys) == 3
        assert all(len(k) == 64 for k in api_keys)

    async def test_create_user_without_telegram_id(
        self, db_session: AsyncSession, create_user
    ):
        # Arrange / Act
        user = await create_user(username="no_telegram", telegram_chat_id=None)

        # Assert
        assert user.id is not None
        assert user.telegram_chat_id is None
        assert user.api_key is not None
