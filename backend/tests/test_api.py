"""
API Tests
=========

Tests for FastAPI endpoints.

These tests use httpx to make requests to the FastAPI app
with a test database.

Run with:
    pytest tests/test_api.py -v
"""

import pytest
from httpx import AsyncClient


# =============================================================================
# Health Check Tests
# =============================================================================


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    async def test_health_check_returns_200(self, test_client: AsyncClient):
        """Test that health check returns 200 OK."""
        response = await test_client.get("/health")

        assert response.status_code == 200

    async def test_health_check_response_structure(self, test_client: AsyncClient):
        """Test health check response contains required fields."""
        response = await test_client.get("/health")
        data = response.json()

        # Check required fields
        assert "status" in data
        assert "version" in data
        assert "environment" in data
        assert "db_connected" in data
        assert "classifier_status" in data

        # Check classifier status structure
        assert "active_layers" in data["classifier_status"]
        assert "setfit_trained" in data["classifier_status"]

    async def test_health_check_db_connected(self, test_client: AsyncClient):
        """Test that database is connected."""
        response = await test_client.get("/health")
        data = response.json()

        assert data["db_connected"] is True

    async def test_health_check_version(self, test_client: AsyncClient):
        """Test that version is returned."""
        response = await test_client.get("/health")
        data = response.json()

        assert data["version"] == "0.1.0"


# =============================================================================
# Root Endpoint Tests
# =============================================================================


class TestRootEndpoint:
    """Tests for the / endpoint."""

    async def test_root_returns_200(self, test_client: AsyncClient):
        """Test that root returns 200 OK."""
        response = await test_client.get("/")

        assert response.status_code == 200

    async def test_root_response_structure(self, test_client: AsyncClient):
        """Test root response contains API info."""
        response = await test_client.get("/")
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "docs" in data
        assert "health" in data

    async def test_root_contains_correct_info(self, test_client: AsyncClient):
        """Test root returns correct app info."""
        response = await test_client.get("/")
        data = response.json()

        assert data["name"] == "Applied"
        assert data["docs"] == "/docs"
        assert data["health"] == "/health"


# =============================================================================
# OpenAPI Documentation Tests
# =============================================================================


class TestDocumentation:
    """Tests for API documentation endpoints."""

    async def test_openapi_schema_available(self, test_client: AsyncClient):
        """Test that OpenAPI schema is available."""
        response = await test_client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()

        assert "openapi" in data
        assert "info" in data
        assert "paths" in data

    async def test_docs_endpoint_available(self, test_client: AsyncClient):
        """Test that Swagger docs are available."""
        response = await test_client.get("/docs")

        # Swagger UI returns HTML
        assert response.status_code == 200

    async def test_redoc_endpoint_available(self, test_client: AsyncClient):
        """Test that ReDoc is available."""
        response = await test_client.get("/redoc")

        # ReDoc returns HTML
        assert response.status_code == 200


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    async def test_404_for_unknown_endpoint(self, test_client: AsyncClient):
        """Test that unknown endpoints return 404."""
        response = await test_client.get("/unknown/endpoint")

        assert response.status_code == 404

    async def test_405_for_wrong_method(self, test_client: AsyncClient):
        """Test that wrong HTTP method returns 405."""
        response = await test_client.post("/health")

        assert response.status_code == 405


# =============================================================================
# CORS Tests
# =============================================================================


class TestCORS:
    """Tests for CORS configuration."""

    async def test_cors_headers_for_localhost(self, test_client: AsyncClient):
        """Test that CORS headers are present for localhost."""
        response = await test_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        # Should allow the origin
        assert response.status_code == 200
