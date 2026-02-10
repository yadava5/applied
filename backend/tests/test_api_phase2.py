"""
Tests for Phase 2 API endpoints.

Tests authentication, sync, and email endpoints.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from jobtracker.main import app


@pytest.fixture
async def test_client():
    """Create test client for API testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# =============================================================================
# Auth Status Endpoint Tests
# =============================================================================


class TestAuthStatus:
    """Tests for /auth/status endpoint."""

    @pytest.mark.asyncio
    async def test_auth_status_no_accounts(self, test_client: AsyncClient):
        """Test auth status with no connected accounts."""
        with patch(
            "jobtracker.api.auth.get_gmail_credentials", return_value=None
        ), patch("jobtracker.api.auth.get_icloud_credentials", return_value=None):
            response = await test_client.get("/auth/status")

            assert response.status_code == 200
            data = response.json()
            assert data["gmail"]["connected"] is False
            assert data["icloud"]["connected"] is False

    @pytest.mark.asyncio
    async def test_auth_status_with_gmail(self, test_client: AsyncClient):
        """Test auth status with Gmail connected."""
        mock_gmail = MagicMock()
        mock_gmail.email = "test@gmail.com"

        with patch(
            "jobtracker.api.auth.get_gmail_credentials", return_value=mock_gmail
        ), patch("jobtracker.api.auth.get_icloud_credentials", return_value=None):
            response = await test_client.get("/auth/status")

            assert response.status_code == 200
            data = response.json()
            assert data["gmail"]["connected"] is True
            assert data["gmail"]["email"] == "test@gmail.com"
            assert data["icloud"]["connected"] is False


# =============================================================================
# Gmail Auth Endpoint Tests
# =============================================================================


class TestGmailClientSecret:
    """Tests for Gmail client secret endpoint."""

    @pytest.mark.asyncio
    async def test_invalid_client_secret_format(self, test_client: AsyncClient):
        """Test rejection of invalid client secret format."""
        response = await test_client.post(
            "/auth/gmail/client-secret",
            json={"client_secret": {"invalid": "format"}},
        )

        assert response.status_code == 400
        assert "installed" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, test_client: AsyncClient):
        """Test rejection of client secret missing required fields."""
        response = await test_client.post(
            "/auth/gmail/client-secret",
            json={
                "client_secret": {
                    "installed": {
                        "client_id": "xxx",
                        # Missing other fields
                    }
                }
            },
        )

        assert response.status_code == 400
        assert "Missing required fields" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_client_secret(self, test_client: AsyncClient):
        """Test successful client secret storage."""
        with patch(
            "jobtracker.api.auth.save_gmail_client_secret", return_value=True
        ):
            response = await test_client.post(
                "/auth/gmail/client-secret",
                json={
                    "client_secret": {
                        "installed": {
                            "client_id": "xxx",
                            "client_secret": "xxx",
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                },
            )

            assert response.status_code == 200
            assert response.json()["success"] is True


# =============================================================================
# iCloud Auth Endpoint Tests
# =============================================================================


class TestICloudAuth:
    """Tests for iCloud authentication endpoint."""

    @pytest.mark.asyncio
    async def test_icloud_auth_invalid_email(self, test_client: AsyncClient):
        """Test rejection of invalid email format."""
        response = await test_client.post(
            "/auth/icloud",
            json={"email": "not-an-email", "app_password": "xxxx-xxxx-xxxx-xxxx"},
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_icloud_auth_short_password(self, test_client: AsyncClient):
        """Test rejection of too-short password."""
        response = await test_client.post(
            "/auth/icloud",
            json={"email": "test@icloud.com", "app_password": "short"},
        )

        assert response.status_code == 422  # Validation error


# =============================================================================
# Disconnect Endpoint Tests
# =============================================================================


class TestDisconnect:
    """Tests for account disconnect endpoints."""

    @pytest.mark.asyncio
    async def test_disconnect_gmail_not_connected(self, test_client: AsyncClient):
        """Test disconnect when Gmail not connected."""
        with patch(
            "jobtracker.api.auth.has_gmail_credentials", return_value=False
        ):
            response = await test_client.delete("/auth/gmail")

            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_disconnect_gmail_success(self, test_client: AsyncClient):
        """Test successful Gmail disconnect."""
        with patch(
            "jobtracker.api.auth.has_gmail_credentials", return_value=True
        ), patch("jobtracker.api.auth.delete_gmail_credentials", return_value=True):
            response = await test_client.delete("/auth/gmail")

            assert response.status_code == 200
            assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_disconnect_icloud_not_connected(self, test_client: AsyncClient):
        """Test disconnect when iCloud not connected."""
        with patch(
            "jobtracker.api.auth.has_icloud_credentials", return_value=False
        ):
            response = await test_client.delete("/auth/icloud")

            assert response.status_code == 404


# =============================================================================
# Sync Endpoint Tests
# =============================================================================


class TestSyncEndpoint:
    """Tests for /sync endpoint."""

    @pytest.mark.asyncio
    async def test_sync_no_accounts(self, test_client: AsyncClient):
        """Test sync with no connected accounts."""
        with patch(
            "jobtracker.api.sync.get_gmail_credentials", return_value=None
        ), patch("jobtracker.api.sync.get_icloud_credentials", return_value=None):
            response = await test_client.post("/sync")

            assert response.status_code == 400
            assert "No email accounts connected" in response.json()["detail"]


# =============================================================================
# Email Endpoints Tests
# =============================================================================


class TestEmailEndpoints:
    """Tests for /emails endpoints."""

    @pytest.mark.asyncio
    async def test_list_emails_empty(self, test_client: AsyncClient):
        """Test listing emails when database is empty."""
        response = await test_client.get("/emails")

        assert response.status_code == 200
        data = response.json()
        assert data["emails"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_email_stats_empty(self, test_client: AsyncClient):
        """Test email stats when database is empty."""
        response = await test_client.get("/emails/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_emails"] == 0

    @pytest.mark.asyncio
    async def test_get_email_not_found(self, test_client: AsyncClient):
        """Test getting non-existent email."""
        response = await test_client.get("/emails/99999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_emails_invalid_source(self, test_client: AsyncClient):
        """Test listing emails with invalid source filter."""
        response = await test_client.get("/emails?source=invalid")

        assert response.status_code == 400
        assert "Invalid source" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_emails_pagination(self, test_client: AsyncClient):
        """Test email list pagination parameters."""
        response = await test_client.get("/emails?page=1&page_size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10


# =============================================================================
# Sync Status Endpoint Tests
# =============================================================================


class TestSyncStatus:
    """Tests for /sync/status endpoint."""

    @pytest.mark.asyncio
    async def test_sync_status_no_state(self, test_client: AsyncClient):
        """Test sync status with no sync state."""
        response = await test_client.get("/sync/status")

        assert response.status_code == 200
        data = response.json()
        assert data["gmail"] is None
        assert data["icloud"] is None
        assert data["last_sync"] is None
