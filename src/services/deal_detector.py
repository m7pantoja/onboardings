"""Servicio de detección de deals ganados en HubSpot."""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from src.clients.hubspot import HubSpotClient, TECHNICIAN_PROPERTIES
from src.models.deal import (
    CompanyInfo,
    ContactPersonInfo,
    EnrichedDeal,
)
from src.models.onboarding import TechnicianInfo
from src.persistence.repository import OnboardingRepository

logger = structlog.get_logger()

# Separadores válidos en el nombre del deal, de más a menos específico
_DEAL_NAME_SEPARATORS = (" - ", " -", "- ", "-")


def parse_deal_name(deal_name: str) -> tuple[str, str]:
    """Parsea 'EMPRESA - SERVICIO' en (company_name, service_name).

    Prueba separadores de más a menos específico. Usa maxsplit=1
    para que guiones extra queden en el nombre del servicio.

    Raises:
        ValueError: si no encuentra un separador que produzca dos partes no vacías.
    """
    for sep in _DEAL_NAME_SEPARATORS:
        parts = deal_name.split(sep, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    raise ValueError(f"No se pudo parsear el nombre del deal: {deal_name!r}")


def extract_technicians(contact_properties: dict[str, str | None]) -> list[TechnicianInfo]:
    """Extrae los técnicos no-nulos del dict de propiedades del contacto."""
    result: list[TechnicianInfo] = []
    for prop_name in TECHNICIAN_PROPERTIES:
        value = contact_properties.get(prop_name)
        if value:
            result.append(TechnicianInfo(hubspot_tec_id=str(value), property_name=prop_name))
    return result


def _build_company_info(company_id: str, props: dict[str, str | None]) -> CompanyInfo:
    """Construye CompanyInfo a partir de las propiedades de HubSpot Company."""
    return CompanyInfo(
        company_id=company_id,
        name=props.get("name", ""),
        nif=props.get("nif"),
        email=props.get("generic_email"),
        phone=props.get("phone"),
        website=props.get("website") or props.get("domain"),
        address=props.get("address"),
        city=props.get("city"),
        state=props.get("state"),
        zip_code=props.get("zip"),
        country=props.get("country"),
        holded_id=props.get("tl_holded_id"),
        drive_folder_id=props.get("drive_folder_id"),
        drive_folder_url=props.get("drive_folder_url"),
    )


def _build_contact_person(contact_id: str, props: dict[str, str | None]) -> ContactPersonInfo:
    """Construye ContactPersonInfo a partir de las propiedades de HubSpot Contact."""
    return ContactPersonInfo(
        contact_id=contact_id,
        firstname=props.get("firstname"),
        lastname=props.get("lastname"),
        full_name=props.get("nombre_y_apellidos"),
        email=props.get("email"),
        phone=props.get("phone"),
        mobile=props.get("mobilephone"),
        job_title=props.get("cargo_en_empresa"),
    )


class DealDetector:
    """Detecta deals WON nuevos en HubSpot y los enriquece con datos de empresa y contacto."""

    def __init__(
        self,
        client: HubSpotClient,
        repository: OnboardingRepository,
        lookback_days: int = 7,
    ) -> None:
        self._client = client
        self._repository = repository
        self._lookback_days = lookback_days

    async def detect_new_deals(self) -> list[EnrichedDeal]:
        """Detecta deals WON nuevos que no hayan sido procesados aún.

        Flujo por cada deal encontrado:
        1. Check idempotencia contra SQLite (ya procesado? → skip)
        2. Parsear deal_name → company_name + service_name
        3. Obtener Company asociada con todas sus propiedades
        4. Obtener Contact (CEO) con propiedades de técnicos y datos personales
        5. Construir EnrichedDeal
        """
        since = datetime.now() - timedelta(days=self._lookback_days)
        new_deals: list[EnrichedDeal] = []

        logger.info(
            "deal_detection_started",
            since=since.isoformat(),
            lookback_days=self._lookback_days,
        )

        async for raw_deal in self._client.search_won_deals(since=since):
            deal_id = int(raw_deal["id"])
            props = raw_deal.get("properties", {})
            deal_name = props.get("dealname", "")

            log = logger.bind(deal_id=deal_id, deal_name=deal_name)

            # 1. Idempotencia: skip si ya existe en BD
            existing = await self._repository.get_by_deal_id(deal_id)
            if existing is not None:
                log.debug("deal_already_processed")
                continue

            # 2. Parsear nombre del deal
            try:
                company_name, service_name = parse_deal_name(deal_name)
            except ValueError:
                log.warning("deal_name_unparseable")
                continue

            # 3. Obtener empresa asociada
            company_id = await self._client.get_deal_company_id(str(deal_id))
            if company_id is None:
                log.warning("deal_has_no_company")
                continue

            company_data = await self._client.get_company(company_id)
            company_props = company_data.get("properties", {})
            company = _build_company_info(company_id, company_props)

            # 4. Obtener contacto principal (CEO)
            contact_ids = await self._client.get_company_contact_ids(company_id)
            if not contact_ids:
                log.warning("company_has_no_contacts", company_id=company_id)
                continue

            if len(contact_ids) > 1:
                log.info(
                    "company_has_multiple_contacts",
                    company_id=company_id,
                    contact_count=len(contact_ids),
                )

            contact_id = contact_ids[0]
            contact_data = await self._client.get_contact(contact_id)
            contact_props = contact_data.get("properties", {})

            contact_person = _build_contact_person(contact_id, contact_props)
            technicians = extract_technicians(contact_props)

            # 5. Construir EnrichedDeal
            close_date = _parse_close_date(props.get("closedate"))

            enriched = EnrichedDeal(
                deal_id=deal_id,
                deal_name=deal_name,
                company_name=company_name,
                service_name=service_name,
                close_date=close_date,
                hubspot_owner_id=(
                    int(props["hubspot_owner_id"]) if props.get("hubspot_owner_id") else None
                ),
                pipeline=props.get("pipeline"),
                dealstage=props.get("dealstage"),
                amount=float(props["amount"]) if props.get("amount") else None,
                company=company,
                contact_person=contact_person,
                technicians=technicians,
            )

            log.info(
                "new_deal_detected",
                company=company_name,
                service=service_name,
                technicians_count=len(technicians),
                holded_exists=company.holded_id is not None,
            )
            new_deals.append(enriched)

        logger.info("deal_detection_completed", new_deals_count=len(new_deals))
        return new_deals


def _parse_close_date(value: str | None) -> datetime:
    """Parsea closedate de HubSpot (ms epoch o ISO string)."""
    if not value:
        return datetime.now()
    try:
        # HubSpot suele devolver ms epoch como string
        return datetime.fromtimestamp(int(value) / 1000)
    except (ValueError, OverflowError):
        pass
    try:
        # Fallback: formato ISO
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()
