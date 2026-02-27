"""Clase base abstracta para los steps del onboarding y contexto compartido."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.models.deal import CompanyInfo, ContactPersonInfo, EnrichedDeal
from src.models.enums import StepName
from src.models.sheets import Department, TeamMember


@dataclass
class StepContext:
    """Datos compartidos entre los steps de un onboarding.

    Se construye a partir de un EnrichedDeal + datos del ServiceMapper,
    y se enriquece a medida que los steps se ejecutan.
    """

    # Datos del deal
    deal_id: int
    deal_name: str
    company_name: str
    service_name: str
    hubspot_owner_id: int | None = None

    # Empresa y contacto (de HubSpot)
    company: CompanyInfo | None = None
    contact_person: ContactPersonInfo | None = None

    # Departamento y técnico (de ServiceMapper + Google Sheet)
    department: Department | None = None
    technician: TeamMember | None = None

    # IDs generados por los steps (se rellenan durante la ejecución)
    drive_folder_id: str | None = None
    drive_folder_url: str | None = None
    drive_subfolder_id: str | None = None
    holded_contact_id: str | None = None
    holded_contact_url: str | None = None

    # HubSpot portal/deal URLs
    hubspot_portal_id: int | None = None

    @property
    def hubspot_deal_url(self) -> str | None:
        if self.hubspot_portal_id and self.deal_id:
            return f"https://app.hubspot.com/contacts/{self.hubspot_portal_id}/deal/{self.deal_id}"
        return None

    @classmethod
    def from_enriched_deal(
        cls,
        deal: EnrichedDeal,
        department: Department,
        technician: TeamMember,
        hubspot_portal_id: int | None = None,
    ) -> StepContext:
        return cls(
            deal_id=deal.deal_id,
            deal_name=deal.deal_name,
            company_name=deal.company_name,
            service_name=deal.service_name,
            hubspot_owner_id=deal.hubspot_owner_id,
            company=deal.company,
            contact_person=deal.contact_person,
            department=department,
            technician=technician,
            # Si ya existe en Holded/Drive, preservar los IDs
            holded_contact_id=deal.company.holded_id if deal.company.holded_id else None,
            hubspot_portal_id=hubspot_portal_id,
        )


@dataclass
class StepResult:
    """Resultado de la ejecución de un step."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BaseStep(ABC):
    """Clase base abstracta para los steps del pipeline de onboarding.

    Cada step:
    1. check_already_done → si devuelve True, se salta (idempotencia)
    2. execute → ejecuta la lógica del step
    """

    @property
    @abstractmethod
    def name(self) -> StepName:
        """Nombre del step (para persistencia y logging)."""

    async def run(self, ctx: StepContext) -> StepResult:
        """Ejecuta el step con check de idempotencia."""
        if await self.check_already_done(ctx):
            return StepResult(success=True, data={"skipped": True})
        return await self.execute(ctx)

    async def check_already_done(self, ctx: StepContext) -> bool:
        """Verifica si el step ya se completó. Por defecto retorna False."""
        return False

    @abstractmethod
    async def execute(self, ctx: StepContext) -> StepResult:
        """Lógica principal del step."""
