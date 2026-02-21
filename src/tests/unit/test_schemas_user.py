from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.schemas.user import UserResponse, UserUpdate
from src.schemas.auth import AuthRequest, AuthResponse


@pytest.mark.unit
class TestUserUpdateSchema:

    def test_valid_partial_update(self):
        schema = UserUpdate(username="new-pro-user")
        assert schema.username == "new-pro-user"
        assert schema.telegram_chat_id is None

    def test_username_too_short_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            UserUpdate(username="ab")

        assert "String should have at least 3 characters" in str(exc_info.value)

    def test_username_too_long_raises_error(self):
        long_name = "a" * 101
        with pytest.raises(ValidationError) as exc_info:
            UserUpdate(username=long_name)

        assert "String should have at most 100 characters" in str(exc_info.value)


@pytest.mark.unit
class TestAuthRequestSchema:

    def test_valid_auth_request(self):
        schema = AuthRequest(username="valid-user")
        assert schema.username == "valid-user"

    def test_auth_request_missing_username_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            AuthRequest()

        assert "Field required" in str(exc_info.value)

    def test_auth_request_username_limits(self):
        with pytest.raises(ValidationError):
            AuthRequest(username="x")

        with pytest.raises(ValidationError):
            AuthRequest(username="x" * 101)


@pytest.mark.unit
class TestOrmModeSchemas:
    """Testing parsing from database objects (from_attributes=True)."""

    class DummyUserModel:
        """SQLAlchemy object mock for tests."""

        def __init__(self, id, username, api_key, telegram_chat_id, created_at):
            self.id = id
            self.username = username
            self.api_key = api_key
            self.telegram_chat_id = telegram_chat_id
            self.created_at = created_at

    def test_user_response_parses_from_orm_object(self):
        now = datetime.now(timezone.utc)

        db_user = self.DummyUserModel(
            id=42,
            username="zero-cobra",
            api_key="super-secret-key",
            telegram_chat_id=123456789,
            created_at=now,
        )

        schema = UserResponse.model_validate(db_user)

        assert schema.id == 42
        assert schema.username == "zero-cobra"
        assert schema.api_key == "super-secret-key"
        assert schema.telegram_chat_id == 123456789
        assert schema.created_at == now

    def test_auth_response_parses_from_orm_object(self):
        db_user = self.DummyUserModel(
            id=10,
            username="tester",
            api_key="test-key",
            telegram_chat_id=None,
            created_at=datetime.now(),
        )

        schema = AuthResponse.model_validate(db_user)

        assert schema.id == 10
        assert schema.username == "tester"
        assert schema.api_key == "test-key"
        # Ensure that AuthResponse ignores unnecessary fields from the database (chat_id, created_at)
        assert not hasattr(schema, "telegram_chat_id")
