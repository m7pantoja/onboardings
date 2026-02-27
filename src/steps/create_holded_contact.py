"""Step: crear contacto de la empresa en Holded."""

from __future__ import annotations

from typing import Any

import structlog

from src.clients.holded import HoldedClient, holded_contact_url
from src.clients.hubspot import HubSpotClient
from src.models.enums import StepName
from src.steps.base import BaseStep, StepContext, StepResult

logger = structlog.get_logger()

# Mapeo básico de países en texto libre a código ISO 2-letter
_COUNTRY_CODES: dict[str, str] = {
    "spain": "ES",
    "españa": "ES",
    "portugal": "PT",
    "france": "FR",
    "francia": "FR",
    "germany": "DE",
    "alemania": "DE",
    "italy": "IT",
    "italia": "IT",
    "united kingdom": "GB",
    "uk": "GB",
    "united states": "US",
    "usa": "US",
}


def _country_to_code(country: str | None) -> str:
    """Convierte texto libre de país a código ISO 2-letter."""
    if not country:
        return "ES"  # Default España
    return _COUNTRY_CODES.get(country.strip().casefold(), "ES")


class CreateHoldedContactStep(BaseStep):
    """Crea un contacto (empresa) en Holded con datos de HubSpot.

    Idempotencia: si `company.holded_id` ya tiene valor, se salta.
    Tras crear, escribe `tl_holded_id` en HubSpot Company.
    """

    def __init__(self, holded_client: HoldedClient, hubspot_client: HubSpotClient) -> None:
        self._holded = holded_client
        self._hubspot = hubspot_client

    @property
    def name(self) -> StepName:
        return StepName.CREATE_HOLDED_CONTACT

    async def check_already_done(self, ctx: StepContext) -> bool:
        if ctx.company and ctx.company.holded_id:
            ctx.holded_contact_id = ctx.company.holded_id
            ctx.holded_contact_url = holded_contact_url(ctx.company.holded_id)
            return True
        return False

    async def execute(self, ctx: StepContext) -> StepResult:
        log = logger.bind(deal_id=ctx.deal_id, company=ctx.company_name)

        if not ctx.company:
            return StepResult(success=False, error="No hay datos de empresa")

        payload = self._build_payload(ctx)
        contact_id = await self._holded.create_contact(payload)

        ctx.holded_contact_id = contact_id
        ctx.holded_contact_url = holded_contact_url(contact_id)

        # Write-back a HubSpot Company
        await self._hubspot.update_company(
            ctx.company.company_id,
            {"tl_holded_id": contact_id},
        )

        log.info(
            "holded_contact_created",
            holded_id=contact_id,
            company_id=ctx.company.company_id,
        )

        return StepResult(
            success=True,
            data={
                "holded_contact_id": contact_id,
                "holded_contact_url": ctx.holded_contact_url,
            },
        )

    def _build_payload(self, ctx: StepContext) -> dict[str, Any]:
        """Construye el payload para la API de Holded siguiendo el mapeo definido."""
        company = ctx.company
        assert company is not None

        # Email: generic_email de la Company, fallback a email del CEO
        email = company.email
        if not email and ctx.contact_person:
            email = ctx.contact_person.email

        payload: dict[str, Any] = {
            "name": company.name,
            "type": "client",
            "code": company.nif or "",
            "email": email or "",
            "phone": company.phone or "",
            "billAddress": {
                "address": company.address or "",
                "city": company.city or "",
                "postalCode": company.zip_code or "",
                "province": company.state or "",
                "country": company.country or "",
                "countryCode": _country_to_code(company.country),
            },
        }

        if company.website:
            payload["socialNetworks"] = {"website": company.website}

        # Persona de contacto (CEO)
        if ctx.contact_person:
            cp = ctx.contact_person
            person: dict[str, str] = {
                "name": cp.display_name,
                "email": cp.email or "",
                "phone": cp.phone or cp.mobile or "",
            }
            if cp.job_title:
                person["cargo"] = cp.job_title
            payload["contactPersons"] = [person]

        return payload
