"""Cliente async para la API de Holded (crear contactos)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

HOLDED_API_BASE = "https://api.holded.com/api/invoicing/v1"


class HoldedError(Exception):
    """Error al comunicarse con la API de Holded."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HoldedClient:
    """Cliente async para Holded API.

    Uso como context manager async:
        async with HoldedClient(api_key="...") as holded:
            contact_id = await holded.create_contact(payload)
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HoldedClient:
        self._client = httpx.AsyncClient(
            base_url=HOLDED_API_BASE,
            headers={"key": self._api_key},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def create_contact(self, payload: dict[str, Any]) -> str:
        """Crea un contacto en Holded y devuelve su ID.

        El payload debe seguir la estructura de la API de Holded:
        {
            "name": "...",
            "type": "client",
            "code": "NIF",
            "email": "...",
            "phone": "...",
            "billAddress": {...},
            "socialNetworks": {"website": "..."},
            "contactPersons": [{...}],
        }
        """
        data = await self._request("POST", "/contacts", json=payload)
        contact_id = data.get("id", "")
        logger.info("holded_contact_created", contact_id=contact_id, name=payload.get("name"))
        return str(contact_id)

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Obtiene un contacto por su ID."""
        return await self._request("GET", f"/contacts/{contact_id}")

    # ── Internals ───────────────────────────────────────────────

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Ejecuta una petición HTTP contra la API de Holded."""
        assert self._client is not None, "Usar como context manager: async with HoldedClient(...)"

        response = await self._client.request(method, url, **kwargs)

        if response.status_code >= 400:
            raise HoldedError(
                f"Holded {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        return response.json()


def holded_contact_url(contact_id: str) -> str:
    """Genera la URL directa a un contacto en Holded."""
    return f"https://app.holded.com/contacts/{contact_id}"
