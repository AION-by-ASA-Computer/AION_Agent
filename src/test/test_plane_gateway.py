from unittest.mock import AsyncMock
import os
import pytest
from fastapi.testclient import TestClient
import httpx

# Set dummy environment variables before importing main to avoid errors
os.environ["PLANE_LOCAL_URL"] = "https://plane.mock-target.local"
os.environ["PLANE_GATEWAY_URL"] = "http://localhost:8010"
os.environ["GATEWAY_PORT"] = "8010"

from src.gateway.plane.main import app


def test_gateway_projects_post_sanitization():
    """Verify project POST response is properly sanitized using Pydantic."""
    with TestClient(app) as client:
        # Prepare mock Plane response (with valid UUID formats and nested structures to test coercion)
        mock_plane_data = {
            "id": "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4",
            "name": "Local Plane Project",
            "identifier": "LPP",
            "network": 2,
            "workspace": {
                "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
                "name": "AION Workspace",
            },
            "description": "Project description",
            "created_at": "2026-07-06T10:00:00Z",
            "updated_at": "2026-07-06T10:05:00Z",
            "extra_metadata": {"created_by": "user-uuid"},
            "nested_unsupported_structs": {"lead": "admin"},
        }
        mock_response = httpx.Response(
            status_code=201,
            headers={"Content-Type": "application/json"},
            json=mock_plane_data,
        )

        # Mock the async request call of the proxy client
        app.state.client.request = AsyncMock(return_value=mock_response)

        # Make the request to the proxy
        response = client.post(
            "/api/v1/workspaces/my-workspace/projects/",
            json={"name": "Local Plane Project", "identifier": "LPP"},
            headers={"Authorization": "Bearer api-key"},
        )

        assert response.status_code == 201
        sanitized_data = response.json()

        # Check fields retained
        assert sanitized_data["id"] == "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4"
        assert sanitized_data["name"] == "Local Plane Project"
        assert sanitized_data["identifier"] == "LPP"
        assert sanitized_data["network"] == 2
        # Coerced from object to flat UUID string
        assert sanitized_data["workspace"] == "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
        assert sanitized_data["description"] == "Project description"
        assert sanitized_data["created_at"] == "2026-07-06T10:00:00Z"
        assert sanitized_data["updated_at"] == "2026-07-06T10:05:00Z"

        # Check fields discarded
        assert "extra_metadata" not in sanitized_data
        assert "nested_unsupported_structs" not in sanitized_data

        # Verify target url called
        app.state.client.request.assert_called_once()
        called_args = app.state.client.request.call_args[1]
        assert called_args["method"] == "POST"
        assert (
            called_args["url"]
            == "https://plane.mock-target.local/api/v1/workspaces/my-workspace/projects/"
        )
        assert called_args["headers"]["authorization"] == "Bearer api-key"


def test_gateway_work_items_get_rewriting_and_sanitization():
    """Verify work-items path is rewritten, 'q' param is remapped, and responses are Pydantic sanitized."""
    with TestClient(app) as client:
        # Mock Response for an issue list (using paginated format and testing aliases/coercions)
        mock_plane_data = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "id": "9f9c7bf5-429c-4573-b68e-5fa7a7b8e19e",
                    "name": "Fix DB validation crash",
                    "project_id": "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4",
                    "workspace_id": {
                        "id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
                        "slug": "my-workspace",
                    },
                    "state_id": "2e8e3d0c-7b81-4cd8-b3d9-482a4d95b5fe",
                    "priority": "high",
                    "description": "<p>Crash details HTML</p>",
                    "assignees": ["assignee-uuid"],
                    "labels": [
                        {"id": "6c8b18a1-5d9e-49b8-a734-631d87e0d37e", "name": "bug"},
                        "05441a12-68be-4cc6-8608-f4db6609be12",
                    ],
                }
            ],
        }
        mock_response = httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json=mock_plane_data,
        )

        app.state.client.request = AsyncMock(return_value=mock_response)

        # Make GET request to /work-items/ with query parameter q=crash
        response = client.get(
            "/api/v1/workspaces/my-workspace/work-items/?q=crash&limit=10",
        )

        assert response.status_code == 200
        sanitized_data = response.json()

        # Verify results lists items are sanitized
        assert "results" in sanitized_data
        results = sanitized_data["results"]
        assert len(results) == 1
        issue = results[0]

        # Verify core fields are present and correctly mapped/coerced
        assert issue["id"] == "9f9c7bf5-429c-4573-b68e-5fa7a7b8e19e"
        assert issue["name"] == "Fix DB validation crash"
        # Mapped from project_id to project
        assert issue["project"] == "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4"
        # Mapped from workspace_id and coerced from dict to UUID string
        assert issue["workspace"] == "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
        # Mapped from state_id to state
        assert issue["state"] == "2e8e3d0c-7b81-4cd8-b3d9-482a4d95b5fe"
        assert issue["priority"] == "high"
        assert issue["description"] == "<p>Crash details HTML</p>"

        # Verify labels elements are coerced to UUID strings
        assert len(issue["labels"]) == 2
        assert "6c8b18a1-5d9e-49b8-a734-631d87e0d37e" in issue["labels"]
        assert "05441a12-68be-4cc6-8608-f4db6609be12" in issue["labels"]

        # Verify discarded fields
        assert "assignees" not in issue

        # Check call arguments (path rewritten and query params updated)
        app.state.client.request.assert_called_once()
        called_args = app.state.client.request.call_args[1]
        assert called_args["method"] == "GET"
        # Path work-items mapped to issues
        assert (
            called_args["url"]
            == "https://plane.mock-target.local/api/v1/workspaces/my-workspace/issues/"
        )
        # 'q' param renamed to 'search'
        assert called_args["params"]["search"] == "crash"
        assert called_args["params"]["limit"] == "10"
        assert "q" not in called_args["params"]


def test_gateway_error_forwarding():
    """Verify errors are forwarded as is."""
    with TestClient(app) as client:
        mock_response = httpx.Response(
            status_code=403,
            headers={"Content-Type": "application/json"},
            json={"error": "Forbidden"},
        )

        app.state.client.request = AsyncMock(return_value=mock_response)

        response = client.get("/api/v1/workspaces/slug/projects/")
        assert response.status_code == 403
        assert response.json() == {"error": "Forbidden"}


def test_gateway_project_creation_recovery():
    """Verify that if project creation returns 400, but the project exists, it recovers with 201."""
    with TestClient(app) as client:
        # Mock responses
        post_response = httpx.Response(
            status_code=400,
            headers={"Content-Type": "application/json"},
            json={"error": "Bad Request"},
        )

        get_response = httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/json"},
            json={
                "results": [
                    {
                        "id": "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4",
                        "name": "Recovered Project",
                        "identifier": "REC",
                        "network": 2,
                        "workspace": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
                        "description": "Recovered",
                    }
                ]
            },
        )

        async def mock_request(method, url, **kwargs):
            if method == "POST":
                return post_response
            elif method == "GET":
                return get_response
            raise ValueError(f"Unexpected request: {method} {url}")

        app.state.client.request = mock_request

        response = client.post(
            "/api/v1/workspaces/my-workspace/projects/",
            json={"name": "Recovered Project", "identifier": "REC"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "c30789bc-9988-4a1d-a9a3-5c8e4d3db2a4"
        assert data["name"] == "Recovered Project"
