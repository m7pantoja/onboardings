"""Tests para el cliente de Google Drive."""

from unittest.mock import patch

import httpx
import pytest
import respx

from src.clients.google_drive import (
    DRIVE_API_BASE,
    GoogleDriveClient,
    GoogleDriveError,
    folder_url,
)


@pytest.fixture
def drive_client():
    """Cliente Drive con auth mockeada."""
    client = GoogleDriveClient()
    client._client = httpx.AsyncClient(
        base_url=DRIVE_API_BASE,
        headers={"Authorization": "Bearer fake-token"},
        timeout=httpx.Timeout(30.0),
    )
    return client


class TestFindFolder:
    @respx.mock
    async def test_finds_existing_folder(self, drive_client: GoogleDriveClient) -> None:
        respx.get(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"files": [{"id": "folder123", "name": "Test"}]})
        )
        result = await drive_client.find_folder("Test", parent_id="parent123")
        assert result == "folder123"

    @respx.mock
    async def test_returns_none_when_not_found(self, drive_client: GoogleDriveClient) -> None:
        respx.get(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"files": []})
        )
        result = await drive_client.find_folder("Nonexistent", parent_id="parent123")
        assert result is None


class TestCreateFolder:
    @respx.mock
    async def test_creates_folder(self, drive_client: GoogleDriveClient) -> None:
        respx.post(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"id": "new_folder_id", "name": "Mi Empresa"})
        )
        result = await drive_client.create_folder("Mi Empresa", parent_id="parent123")
        assert result == "new_folder_id"

    @respx.mock
    async def test_raises_on_error(self, drive_client: GoogleDriveClient) -> None:
        respx.post(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        with pytest.raises(GoogleDriveError) as exc_info:
            await drive_client.create_folder("Test", parent_id="parent123")
        assert exc_info.value.status_code == 403


class TestFindOrCreateFolder:
    @respx.mock
    async def test_returns_existing_folder(self, drive_client: GoogleDriveClient) -> None:
        respx.get(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"files": [{"id": "existing_id", "name": "Test"}]})
        )
        result = await drive_client.find_or_create_folder("Test", parent_id="parent123")
        assert result == "existing_id"

    @respx.mock
    async def test_creates_when_not_found(self, drive_client: GoogleDriveClient) -> None:
        respx.get(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"files": []})
        )
        respx.post(f"{DRIVE_API_BASE}/files").mock(
            return_value=httpx.Response(200, json={"id": "created_id", "name": "Test"})
        )
        result = await drive_client.find_or_create_folder("Test", parent_id="parent123")
        assert result == "created_id"


class TestFolderUrl:
    def test_generates_correct_url(self) -> None:
        assert folder_url("abc123") == "https://drive.google.com/drive/folders/abc123"
