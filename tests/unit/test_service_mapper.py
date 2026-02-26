"""Tests para el ServiceMapper."""

from unittest.mock import AsyncMock

import pytest

from src.clients.google_sheets import GoogleSheetsClient
from src.models.sheets import Department, ServiceEntry, TeamMember
from src.services.service_mapper import (
    DepartmentNotAssignedError,
    ServiceMapper,
    ServiceNotFoundError,
)


# ── Fixtures ─────────────────────────────────────────────────────


SAMPLE_SERVICES = [
    ServiceEntry(nombre="Asesoramiento fiscal y contable", tags="asesoria recurrente", department=Department.AS),
    ServiceEntry(nombre="Préstamo ENISA", tags="financiacionpublica oneshot", department=Department.SU),
    ServiceEntry(nombre="Lean Finance CFO", tags="cfo recurrente", department=Department.FI),
    ServiceEntry(nombre="Gestión laboral", tags="asesoria recurrente", department=Department.LA),
    ServiceEntry(nombre="Servicios DATA", tags="serviciosdata recurrente", department=Department.DA),
    # Sin departamento
    ServiceEntry(nombre="SaaS Growth", tags="partnerships oneshot", department=None),
]

SAMPLE_MEMBERS = [
    TeamMember(
        hubspot_tec_id="1404036103", slack_id="U02QKGE0QP6",
        email="candido@leanfinance.es", nombre_completo="Candi Diaz",
        nombre_corto="Candi", department=Department.SU, is_responsable=False,
    ),
    TeamMember(
        hubspot_tec_id="1812229188", slack_id="U04TAKKLT9R",
        email="joseangel@leanfinance.es", nombre_completo="Jose Ángel Pérez Vidal",
        nombre_corto="Jose Ángel", department=Department.SU, is_responsable=True,
    ),
    TeamMember(
        hubspot_tec_id="76339094", slack_id="U06MRGSBQS3",
        email="esther@leanfinance.es", nombre_completo="Esther Punzano López",
        nombre_corto="Esther", department=Department.AS, is_responsable=True,
    ),
]


@pytest.fixture
def mock_sheets() -> GoogleSheetsClient:
    client = AsyncMock(spec=GoogleSheetsClient)
    client.fetch_services = AsyncMock(return_value=SAMPLE_SERVICES)
    client.fetch_team_members = AsyncMock(return_value=SAMPLE_MEMBERS)
    return client


@pytest.fixture
def mapper(mock_sheets: GoogleSheetsClient) -> ServiceMapper:
    return ServiceMapper(mock_sheets)


# ── Tests de get_department ──────────────────────────────────────


class TestGetDepartment:
    async def test_exact_match(self, mapper: ServiceMapper) -> None:
        dept = await mapper.get_department("Préstamo ENISA")
        assert dept == Department.SU

    async def test_case_insensitive(self, mapper: ServiceMapper) -> None:
        dept = await mapper.get_department("préstamo enisa")
        assert dept == Department.SU

    async def test_whitespace_tolerant(self, mapper: ServiceMapper) -> None:
        dept = await mapper.get_department("  Préstamo ENISA  ")
        assert dept == Department.SU

    async def test_service_not_found_raises(self, mapper: ServiceMapper) -> None:
        with pytest.raises(ServiceNotFoundError) as exc_info:
            await mapper.get_department("Servicio Inexistente")
        assert "Servicio Inexistente" in str(exc_info.value)

    async def test_service_without_department_raises(self, mapper: ServiceMapper) -> None:
        with pytest.raises(DepartmentNotAssignedError) as exc_info:
            await mapper.get_department("SaaS Growth")
        assert "SaaS Growth" in str(exc_info.value)

    async def test_all_departments(self, mapper: ServiceMapper) -> None:
        assert await mapper.get_department("Asesoramiento fiscal y contable") == Department.AS
        assert await mapper.get_department("Lean Finance CFO") == Department.FI
        assert await mapper.get_department("Gestión laboral") == Department.LA
        assert await mapper.get_department("Servicios DATA") == Department.DA


# ── Tests de get_team_members ────────────────────────────────────


class TestGetTeamMembers:
    async def test_filter_by_department(self, mapper: ServiceMapper) -> None:
        members = await mapper.get_team_members(Department.SU)
        assert len(members) == 2
        assert all(m.department == Department.SU for m in members)

    async def test_empty_department(self, mapper: ServiceMapper) -> None:
        members = await mapper.get_team_members(Department.DI)
        assert members == []


# ── Tests de get_responsable ─────────────────────────────────────


class TestGetResponsable:
    async def test_returns_responsable(self, mapper: ServiceMapper) -> None:
        resp = await mapper.get_responsable(Department.SU)
        assert resp is not None
        assert resp.nombre_corto == "Jose Ángel"
        assert resp.is_responsable is True

    async def test_no_responsable_returns_none(self, mapper: ServiceMapper) -> None:
        resp = await mapper.get_responsable(Department.DI)
        assert resp is None
