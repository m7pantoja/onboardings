from datetime import datetime

from pydantic import BaseModel, Field

from src.models.onboarding import TechnicianInfo


class Deal(BaseModel):
    """Deal de HubSpot parseado."""

    deal_id: int
    deal_name: str
    company_name: str
    service_name: str
    amount: float | None = None
    hubspot_owner_id: int | None = None
    pipeline: str | None = None
    dealstage: str | None = None


class CompanyInfo(BaseModel):
    """Datos de la empresa desde HubSpot Company."""

    company_id: str
    name: str
    nif: str | None = None
    email: str | None = None  # generic_email de la Company
    phone: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None
    holded_id: str | None = None  # tl_holded_id — si tiene valor, ya existe en Holded


class ContactPersonInfo(BaseModel):
    """Datos de la persona de contacto (CEO) desde HubSpot Contact."""

    contact_id: str
    firstname: str | None = None
    lastname: str | None = None
    full_name: str | None = None  # nombre_y_apellidos (custom)
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    job_title: str | None = None  # cargo_en_empresa

    @property
    def display_name(self) -> str:
        """Nombre para mostrar, priorizando nombre_y_apellidos."""
        if self.full_name:
            return self.full_name
        parts = [p for p in (self.firstname, self.lastname) if p]
        return " ".join(parts) if parts else self.email or ""


class EnrichedDeal(BaseModel):
    """Deal enriquecido con datos de empresa, contacto y técnicos.

    Resultado de la detección: listo para entrar al pipeline de onboarding.
    """

    # Deal
    deal_id: int
    deal_name: str
    company_name: str  # parseado del deal_name
    service_name: str  # parseado del deal_name
    close_date: datetime
    hubspot_owner_id: int | None = None
    pipeline: str | None = None
    dealstage: str | None = None
    amount: float | None = None

    # Empresa y contacto
    company: CompanyInfo
    contact_person: ContactPersonInfo

    # Técnicos
    technicians: list[TechnicianInfo] = Field(default_factory=list)
