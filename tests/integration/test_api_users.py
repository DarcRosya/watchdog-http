import pytest
from httpx import AsyncClient

from src.models.user import User


@pytest.mark.api
@pytest.mark.integration
class TestUsersAPI:

    # --- POST /users/ ------------------------------------------------------

    async def test_create_user_returns_201_with_valid_response_shape(
        self, client: AsyncClient
    ):
        response = await client.post("/users/")

        assert response.status_code == 201
        data = response.json()
        assert all(key in data for key in ("id", "username", "api_key", "created_at"))
        assert data["id"] is not None
        assert len(data["api_key"]) == 64

    async def test_create_user_generates_unique_usernames(self, client: AsyncClient):
        r1 = await client.post("/users/")
        r2 = await client.post("/users/")

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["username"] != r2.json()["username"]

    async def test_create_user_generates_unique_api_keys(self, client: AsyncClient):
        r1 = await client.post("/users/")
        r2 = await client.post("/users/")

        assert r1.json()["api_key"] != r2.json()["api_key"]

    # --- POST /users/auth --------------------------------------------------

    async def test_auth_returns_api_key_for_existing_user(
        self, client: AsyncClient, sample_user: User
    ):
        response = await client.post(
            "/users/auth", json={"username": sample_user.username}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == sample_user.api_key
        assert data["username"] == sample_user.username

    async def test_auth_returns_404_for_unknown_username(self, client: AsyncClient):
        response = await client.post(
            "/users/auth", json={"username": "totally_unknown_user"}
        )

        assert response.status_code == 404

    async def test_auth_returns_422_when_username_too_short(self, client: AsyncClient):
        response = await client.post("/users/auth", json={"username": "ab"})

        assert response.status_code == 422

    # --- GET /users/me -----------------------------------------------------

    async def test_get_me_returns_current_user(
        self, client: AsyncClient, sample_user: User, auth_headers: dict
    ):
        response = await client.get("/users/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_user.id
        assert data["username"] == sample_user.username
        assert data["api_key"] == sample_user.api_key

    async def test_get_me_returns_401_without_api_key(self, client: AsyncClient):
        response = await client.get("/users/me")

        assert response.status_code == 401

    async def test_get_me_returns_401_with_invalid_api_key(self, client: AsyncClient):
        response = await client.get("/users/me", headers={"X-API-Key": "bad-key"})

        assert response.status_code == 401

    # --- PATCH /users/me ---------------------------------------------------

    async def test_update_me_changes_username(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.patch(
            "/users/me",
            json={"username": "new_username_xyz"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["username"] == "new_username_xyz"

    async def test_update_me_sets_telegram_chat_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.patch(
            "/users/me",
            json={"telegram_chat_id": 987654321},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["telegram_chat_id"] == 987654321

    async def test_update_me_clears_telegram_chat_id_when_null(
        self, client: AsyncClient, create_user, db_session
    ):
        # User already has a telegram_chat_id; patch it to null
        user = await create_user(username="tg_user", telegram_chat_id=111222333)
        headers = {"X-API-Key": user.api_key}

        response = await client.patch(
            "/users/me", json={"telegram_chat_id": None}, headers=headers
        )

        assert response.status_code == 200
        assert response.json()["telegram_chat_id"] is None

    async def test_update_me_returns_401_without_auth(self, client: AsyncClient):
        response = await client.patch("/users/me", json={"username": "hacker"})

        assert response.status_code == 401

    async def test_update_me_returns_422_when_username_too_short(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.patch(
            "/users/me", json={"username": "ab"}, headers=auth_headers
        )

        assert response.status_code == 422

    # --- GET /users/{id} ---------------------------------------------------

    async def test_get_user_by_id_returns_correct_user(
        self, client: AsyncClient, sample_user: User, auth_headers: dict
    ):
        response = await client.get(f"/users/{sample_user.id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_user.id
        assert data["username"] == sample_user.username

    async def test_get_user_by_id_returns_404_for_nonexistent_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/users/999999", headers=auth_headers)

        assert response.status_code == 404

    async def test_get_user_by_id_returns_401_without_auth(self, client: AsyncClient):
        response = await client.get("/users/1")

        assert response.status_code == 401

    # --- GET /users/telegram/{telegram_id} ---------------------------------

    async def test_get_user_by_telegram_id_returns_correct_user(
        self, client: AsyncClient, create_user, auth_headers: dict
    ):
        # Arrange
        tg_id = 77665544
        user = await create_user(username="tg_lookup_user", telegram_chat_id=tg_id)

        response = await client.get(f"/users/telegram/{tg_id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["id"] == user.id

    async def test_get_user_by_telegram_id_returns_404_when_not_found(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/users/telegram/99999999", headers=auth_headers)

        assert response.status_code == 404

    async def test_get_user_by_telegram_id_returns_401_without_auth(
        self, client: AsyncClient
    ):
        response = await client.get("/users/telegram/12345")

        assert response.status_code == 401
