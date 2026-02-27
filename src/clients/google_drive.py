"""Cliente async para Google Drive API v3 (crear carpetas en Shared Drive)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from src.clients.google_auth import get_google_credentials

logger = structlog.get_logger()

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class GoogleDriveError(Exception):
    """Error al comunicarse con la Google Drive API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleDriveClient:
    """Cliente async para crear carpetas en Google Drive (Shared Drive).

    Uso como context manager async:
        async with GoogleDriveClient() as drive:
            folder_id = await drive.find_or_create_folder("Mi Empresa", parent_id="...")
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GoogleDriveClient:
        creds = get_google_credentials()
        self._client = httpx.AsyncClient(
            base_url=DRIVE_API_BASE,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def find_folder(self, name: str, parent_id: str) -> str | None:
        """Busca una carpeta por nombre dentro de un padre. Devuelve el ID o None."""
        assert self._client is not None

        # Escapar comillas simples en el nombre
        safe_name = name.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' "
            f"and '{parent_id}' in parents "
            f"and mimeType = '{FOLDER_MIME_TYPE}' "
            f"and trashed = false"
        )
        params = {
            "q": query,
            "fields": "files(id, name)",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "corpora": "allDrives",
        }

        data = await self._request("GET", "/files", params=params)
        files = data.get("files", [])

        if files:
            folder_id = files[0]["id"]
            logger.debug("drive_folder_found", name=name, folder_id=folder_id)
            return folder_id

        return None

    async def create_folder(self, name: str, parent_id: str) -> str:
        """Crea una carpeta y devuelve su ID."""
        assert self._client is not None

        metadata: dict[str, Any] = {
            "name": name,
            "mimeType": FOLDER_MIME_TYPE,
            "parents": [parent_id],
        }

        data = await self._request(
            "POST",
            "/files",
            json=metadata,
            params={"supportsAllDrives": "true", "fields": "id, name"},
        )

        folder_id = data["id"]
        logger.info("drive_folder_created", name=name, folder_id=folder_id, parent_id=parent_id)
        return folder_id

    async def find_or_create_folder(self, name: str, parent_id: str) -> str:
        """Busca una carpeta por nombre; si no existe, la crea. Devuelve el ID."""
        existing = await self.find_folder(name, parent_id)
        if existing:
            return existing
        return await self.create_folder(name, parent_id)

    # ── Internals ───────────────────────────────────────────────

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Ejecuta una petición HTTP contra la API de Drive."""
        assert self._client is not None

        response = await self._client.request(method, url, **kwargs)

        if response.status_code >= 400:
            raise GoogleDriveError(
                f"Google Drive {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        return response.json()


def folder_url(folder_id: str) -> str:
    """Genera la URL directa a una carpeta de Google Drive."""
    return f"https://drive.google.com/drive/folders/{folder_id}"
