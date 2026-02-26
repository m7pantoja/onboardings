"""Modelos para los datos de la Google Sheet 'matriz-onboardings'."""

from enum import StrEnum

from pydantic import BaseModel


class Department(StrEnum):
    """Departamentos de LeanFinance (códigos de la Sheet)."""

    SU = "SU"  # Financiación Pública
    FI = "FI"  # CFO
    AS = "AS"  # Asesoría fiscal
    LA = "LA"  # Asesoría laboral
    LE = "LE"  # Legal
    DA = "DA"  # Servicios DATA
    DI = "DI"  # Diseño


DEPARTMENT_LABELS: dict[Department, str] = {
    Department.SU: "Financiación Pública",
    Department.FI: "CFO",
    Department.AS: "Asesoría fiscal",
    Department.LA: "Asesoría laboral",
    Department.LE: "Legal",
    Department.DA: "Servicios DATA",
    Department.DI: "Diseño",
}


class TeamMember(BaseModel):
    """Miembro del equipo (hoja 'usuarios')."""

    hubspot_tec_id: str | None = None
    slack_id: str | None = None
    email: str
    nombre_completo: str
    nombre_corto: str
    department: Department
    is_responsable: bool = False


class ServiceEntry(BaseModel):
    """Servicio con su departamento (hoja 'servicios')."""

    nombre: str
    tags: str | None = None
    department: Department | None = None
