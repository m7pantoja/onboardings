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


# Propiedades de HubSpot Contact que contienen el hubspot_tec_id, por departamento.
# Si el departamento no aparece aquí, el "técnico" es el responsable del depto.
DEPARTMENT_TECHNICIAN_PROPERTIES: dict[Department, tuple[str, ...]] = {
    Department.SU: ("tecnico_enisa_asignado", "tecnico_subvencion_asignado"),
    Department.FI: ("cfo_asignado", "cfo_asignado_ii"),
    Department.AS: ("asesor_fiscal_asignado", "administrativo_asignado"),
    Department.LA: ("asesor_laboral_asignado",),
}

# Subcarpetas de Drive que se crean dentro de la carpeta del cliente.
# Si el departamento no aparece aquí, no se crea subcarpeta.
DEPARTMENT_DRIVE_SUBFOLDER: dict[Department, str] = {
    Department.SU: "03 - Financiación Pública",
    Department.FI: "01 - CFO",
    Department.AS: "02 - Asesoría fiscal, contable y laboral",
    Department.LA: "02 - Asesoría fiscal, contable y laboral",
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
