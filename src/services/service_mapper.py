"""Mapea servicios a departamentos usando la Google Sheet 'matriz-onboardings'."""

from __future__ import annotations

import structlog

from src.clients.google_sheets import GoogleSheetsClient
from src.models.sheets import Department, ServiceEntry, TeamMember

logger = structlog.get_logger()


class ServiceNotFoundError(Exception):
    """El servicio no existe en la Google Sheet."""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(f"Servicio no encontrado en la Sheet: {service_name!r}")


class DepartmentNotAssignedError(Exception):
    """El servicio existe pero no tiene departamento asignado."""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(f"Servicio sin departamento asignado: {service_name!r}")


class ServiceMapper:
    """Resuelve servicio → departamento y expone datos del equipo.

    Uso:
        async with GoogleSheetsClient(spreadsheet_id="...") as sheets:
            mapper = ServiceMapper(sheets)
            dept = await mapper.get_department("Préstamo ENISA")
            responsable = await mapper.get_responsable(dept)
    """

    def __init__(self, sheets_client: GoogleSheetsClient) -> None:
        self._sheets = sheets_client

    async def get_department(self, service_name: str) -> Department:
        """Busca el departamento para un servicio.

        Raises:
            ServiceNotFoundError: si el servicio no aparece en la Sheet.
            DepartmentNotAssignedError: si el servicio existe pero no tiene departamento.
        """
        services = await self._sheets.fetch_services()
        normalized = _normalize(service_name)

        match: ServiceEntry | None = None
        for entry in services:
            if _normalize(entry.nombre) == normalized:
                match = entry
                break

        if match is None:
            logger.warning("service_not_found", service_name=service_name)
            raise ServiceNotFoundError(service_name)

        if match.department is None:
            logger.warning("service_no_department", service_name=service_name)
            raise DepartmentNotAssignedError(service_name)

        logger.info(
            "service_mapped",
            service=service_name,
            department=match.department.value,
        )
        return match.department

    async def get_team_members(self, department: Department) -> list[TeamMember]:
        """Devuelve todos los miembros de un departamento."""
        members = await self._sheets.fetch_team_members()
        return [m for m in members if m.department == department]

    async def get_responsable(self, department: Department) -> TeamMember | None:
        """Devuelve el responsable de un departamento, o None si no hay ninguno marcado."""
        members = await self.get_team_members(department)
        for m in members:
            if m.is_responsable:
                return m
        logger.warning("no_responsable_found", department=department.value)
        return None


def _normalize(name: str) -> str:
    """Normaliza un nombre de servicio para comparación."""
    return name.strip().casefold()
