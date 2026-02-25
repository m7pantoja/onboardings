from pydantic import BaseModel


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
