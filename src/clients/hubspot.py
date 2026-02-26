"""Cliente async para la API de HubSpot CRM v3."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

BASE_URL = "https://api.hubapi.com"
PIPELINE_ID = "20024183"
WON_STAGE_ID = "48577422"
MAX_RETRIES = 3

DEAL_PROPERTIES: tuple[str, ...] = (
    "dealname",
    "amount",
    "hubspot_owner_id",
    "pipeline",
    "dealstage",
    "closedate",
)

COMPANY_PROPERTIES: tuple[str, ...] = (
    "name",
    "nif",
    "generic_email",
    "phone",
    "address",
    "city",
    "state",
    "zip",
    "country",
    "website",
    "domain",
    "tl_holded_id",
    "tl_synced_holded",
)

# Propiedades de técnicos + datos de la persona de contacto
TECHNICIAN_PROPERTIES: tuple[str, ...] = (
    "tecnico_enisa_asignado",
    "tecnico_subvencion_asignado",
    "cfo_asignado",
    "cfo_asignado_ii",
    "asesor_fiscal_asignado",
    "asesor_laboral_asignado",
    "administrativo_asignado",
)

CONTACT_PROPERTIES: tuple[str, ...] = (
    "firstname",
    "lastname",
    "nombre_y_apellidos",
    "email",
    "phone",
    "mobilephone",
    "cargo_en_empresa",
    "nif",
    *TECHNICIAN_PROPERTIES,
)


class HubSpotError(Exception):
    """Error al comunicarse con la API de HubSpot."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HubSpotClient:
    """Cliente async para HubSpot CRM API v3.

    Uso como context manager async:
        async with HubSpotClient(token="...") as client:
            async for deal in client.search_won_deals(since=...):
                ...
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HubSpotClient:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def search_won_deals(self, since: datetime) -> AsyncIterator[dict[str, Any]]:
        """Busca deals en stage Won desde `since`. Maneja paginación automáticamente."""
        since_ms = str(int(since.timestamp() * 1000))
        after: str | None = None

        while True:
            body: dict[str, Any] = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "pipeline",
                                "operator": "EQ",
                                "value": PIPELINE_ID,
                            },
                            {
                                "propertyName": "dealstage",
                                "operator": "EQ",
                                "value": WON_STAGE_ID,
                            },
                            {
                                "propertyName": "closedate",
                                "operator": "GTE",
                                "value": since_ms,
                            },
                        ]
                    }
                ],
                "properties": list(DEAL_PROPERTIES),
                "limit": 100,
            }
            if after:
                body["after"] = after

            data = await self._request("POST", "/crm/v3/objects/deals/search", json=body)

            for result in data.get("results", []):
                yield result

            paging = data.get("paging", {})
            after = paging.get("next", {}).get("after")
            if not after:
                break

    async def get_company(self, company_id: str) -> dict[str, Any]:
        """Obtiene las propiedades de una empresa."""
        params = {"properties": ",".join(COMPANY_PROPERTIES)}
        return await self._request(
            "GET", f"/crm/v3/objects/companies/{company_id}", params=params
        )

    async def get_deal_company_id(self, deal_id: str) -> str | None:
        """Devuelve el company_id asociado al deal, o None si no tiene."""
        data = await self._request(
            "GET", f"/crm/v3/objects/deals/{deal_id}/associations/companies"
        )
        results = data.get("results", [])
        if not results:
            return None
        return str(results[0]["toObjectId"])

    async def get_company_contact_ids(self, company_id: str) -> list[str]:
        """Devuelve los contact_ids asociados a la empresa."""
        data = await self._request(
            "GET", f"/crm/v3/objects/companies/{company_id}/associations/contacts"
        )
        return [str(r["toObjectId"]) for r in data.get("results", [])]

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Obtiene las propiedades de un contacto (persona de contacto + técnicos)."""
        params = {"properties": ",".join(CONTACT_PROPERTIES)}
        return await self._request(
            "GET", f"/crm/v3/objects/contacts/{contact_id}", params=params
        )

    # ── Internals ───────────────────────────────────────────────

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Ejecuta una petición HTTP con retry para 429 y 5xx."""
        assert self._client is not None, "Usar como context manager: async with HubSpotClient(...)"

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                wait = 2**attempt
                logger.warning(
                    "hubspot_request_error",
                    method=method, url=url, attempt=attempt + 1, error=str(exc),
                )
                await asyncio.sleep(wait)
                continue

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "10"))
                logger.warning(
                    "hubspot_rate_limited",
                    method=method, url=url, retry_after=retry_after,
                )
                await asyncio.sleep(retry_after)
                continue

            if response.status_code >= 500:
                wait = 2**attempt
                logger.warning(
                    "hubspot_server_error",
                    method=method, url=url, status=response.status_code,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)
                continue

            if response.status_code >= 400:
                raise HubSpotError(
                    f"HubSpot {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

            return response.json()

        raise HubSpotError(
            f"Max reintentos ({MAX_RETRIES}) superados para {method} {url}",
            status_code=getattr(last_error, "status_code", None),
        )
