import pytest
from httpx import AsyncClient

from src.models.user import User


@pytest.mark.api
@pytest.mark.integration
class TestMonitorsAPI:

    # --- GET /monitors/ ----------------------------------------------------

    async def test_get_monitors_returns_list_for_authenticated_user(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        await create_monitor(
            user_id=sample_user.id, url="https://test1.com", name="Monitor 1"
        )
        await create_monitor(
            user_id=sample_user.id, url="https://test2.com", name="Monitor 2"
        )
        await create_monitor(
            user_id=sample_user.id, url="https://test3.com", name="Monitor 3"
        )

        # Act
        response = await client.get("/monitors/", headers=auth_headers)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3
        assert all(key in data[0] for key in ("id", "url", "name", "is_active"))

    async def test_get_monitors_returns_401_without_api_key(self, client: AsyncClient):
        # Arrange – no headers

        # Act
        response = await client.get("/monitors/")

        # Assert
        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    async def test_get_monitors_returns_401_with_invalid_api_key(
        self, client: AsyncClient
    ):
        # Arrange
        headers = {"X-API-Key": "invalid_test_key_12345"}

        # Act
        response = await client.get("/monitors/", headers=headers)

        # Assert
        assert response.status_code == 401

    # --- GET /monitors/{id} ------------------------------------------------

    async def test_get_monitor_by_id_returns_correct_monitor(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        monitor = await create_monitor(
            user_id=sample_user.id, url="https://test-target.com", name="Target Monitor"
        )

        # Act
        response = await client.get(f"/monitors/{monitor.id}", headers=auth_headers)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == monitor.id
        assert data["url"].rstrip("/") == monitor.url.rstrip("/")
        assert data["name"] == monitor.name

    async def test_get_monitor_by_id_returns_404_for_nonexistent_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        # Arrange
        non_existent_id = 999999

        # Act
        response = await client.get(
            f"/monitors/{non_existent_id}", headers=auth_headers
        )

        # Assert
        assert response.status_code == 404

    # --- POST /monitors/add-urls -------------------------------------------

    async def test_create_monitors_bulk_creates_all_provided_urls(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        # Arrange – endpoint accepts List[MonitorCreate], one object per URL
        payload = [
            {"url": "https://example1.com", "name": "Bulk Monitor", "interval": 120},
            {"url": "https://example2.com", "name": "Bulk Monitor", "interval": 120},
        ]

        # Act
        response = await client.post(
            "/monitors/add-urls", json=payload, headers=auth_headers
        )

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert len(data) == 2
        assert all(m["name"] == "Bulk Monitor" for m in data)
        assert all(m["interval"] == 120 for m in data)

    async def test_create_monitors_returns_422_for_invalid_url(
        self, client: AsyncClient, auth_headers: dict
    ):
        # Arrange
        payload = [{"url": "not-a-valid-url", "interval": 60}]

        # Act
        response = await client.post(
            "/monitors/add-urls", json=payload, headers=auth_headers
        )

        # Assert
        assert response.status_code == 422

    # --- PATCH /monitors/{id} ----------------------------------------------

    async def test_update_monitor_applies_new_values(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        monitor = await create_monitor(
            user_id=sample_user.id,
            url="https://test-update.com",
            name="Original Name",
            interval=60,
        )
        update_payload = {"name": "Updated Name", "interval": 180}

        # Act
        response = await client.patch(
            f"/monitors/{monitor.id}", json=update_payload, headers=auth_headers
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == monitor.id
        assert data["name"] == "Updated Name"
        assert data["interval"] == 180

    async def test_update_monitor_returns_404_for_nonexistent_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        # Arrange
        update_payload = {"name": "Should Fail"}

        # Act
        response = await client.patch(
            "/monitors/999999", json=update_payload, headers=auth_headers
        )

        # Assert
        assert response.status_code == 404

    # --- DELETE /monitors/{id} ---------------------------------------------

    async def test_delete_monitor_removes_it_from_the_database(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        monitor = await create_monitor(
            user_id=sample_user.id, url="https://test-delete.com", name="To Be Deleted"
        )

        # Act
        response = await client.delete(f"/monitors/{monitor.id}", headers=auth_headers)

        # Assert
        assert response.status_code in (200, 204)
        get_response = await client.get(f"/monitors/{monitor.id}", headers=auth_headers)
        assert get_response.status_code == 404

    # --- PATCH /monitors/{id}/toggle ---------------------------------------

    async def test_toggle_deactivates_an_active_monitor(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        monitor = await create_monitor(
            user_id=sample_user.id, url="https://toggle-off-test.com", is_active=True
        )

        # Act
        response = await client.patch(
            f"/monitors/{monitor.id}/toggle", headers=auth_headers
        )

        # Assert
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    async def test_toggle_activates_an_inactive_monitor(
        self,
        client: AsyncClient,
        sample_user: User,
        create_monitor,
        auth_headers: dict,
    ):
        # Arrange
        monitor = await create_monitor(
            user_id=sample_user.id, url="https://toggle-on-test.com", is_active=False
        )

        # Act
        response = await client.patch(
            f"/monitors/{monitor.id}/toggle", headers=auth_headers
        )

        # Assert
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    # --- Isolation ---------------------------------------------------------

    async def test_user_can_only_see_their_own_monitors(
        self,
        client: AsyncClient,
        create_user,
        create_monitor,
    ):
        # Arrange
        user1 = await create_user(username="isolation_user1")
        user2 = await create_user(username="isolation_user2")
        monitor1 = await create_monitor(
            user_id=user1.id, url="https://user1-monitor.com"
        )
        await create_monitor(user_id=user2.id, url="https://user2-monitor.com")

        # Act
        response = await client.get("/monitors/", headers={"X-API-Key": user1.api_key})

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == monitor1.id
