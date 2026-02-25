from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import OnboardingStatus, StepName, StepStatus


class TechnicianInfo(BaseModel):
    """Técnico asignado al onboarding."""

    hubspot_tec_id: str
    property_name: str  # ej: "tecnico_enisa_asignado"


class StepRecord(BaseModel):
    """Estado persistido de un step individual."""

    onboarding_id: int
    step_name: StepName
    status: StepStatus = StepStatus.PENDING
    result_data: dict | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class OnboardingRecord(BaseModel):
    """Estado persistido de un onboarding completo."""

    id: int | None = None
    deal_id: int
    deal_name: str
    company_name: str
    service_name: str
    department: str | None = None
    hubspot_owner_id: int | None = None  # Comercial que cerró el deal
    technicians: list[TechnicianInfo] = Field(default_factory=list)
    status: OnboardingStatus = OnboardingStatus.PENDING
    current_step: StepName | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    steps: list[StepRecord] = Field(default_factory=list)
