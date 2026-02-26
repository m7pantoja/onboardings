"""Tests para el parsing de datos de la Google Sheet."""

import pytest

from src.clients.google_sheets import _parse_services, _parse_team_members
from src.models.sheets import Department


# ── Datos de ejemplo (simulan lo que devuelve la API de Sheets) ──


USERS_ROWS = [
    ["hubspot_tec_id", "slack_id", "email", "nombre_completo", "nombre_corto", "departamento", "responsable"],
    ["1404036103", "U02QKGE0QP6", "candido@leanfinance.es", "Candi Diaz", "Candi", "SU", "FALSE"],
    ["1812229188", "U04TAKKLT9R", "joseangel@leanfinance.es", "Jose Ángel Pérez Vidal", "Jose Ángel", "SU", "TRUE"],
    ["76339094", "U06MRGSBQS3", "esther@leanfinance.es", "Esther Punzano López", "Esther", "AS", "TRUE"],
    ["76339100", "U07KLD0N37E", "sergio@leanfinance.es", "Sergio Gónzalez", "Sergio", "LA", "TRUE"],
    # Sin hubspot_tec_id
    ["", "U0AFV38PLFQ", "adelcarmen@leanfinance.es", "Abraham", "Abraham", "FI", "FALSE"],
    # Sin columna responsable (solo 6 columnas)
    ["87876606", "U0A8SHFD5QD", "tech@leanfinance.es", "Tech Lean Finance", "Tech Lean Finance", "DA"],
]

SERVICES_ROWS = [
    ["nombre", "tags", "departmento"],
    ["Asesoramiento fiscal y contable", "asesoria recurrente", "AS"],
    ["Préstamo ENISA", "financiacionpublica oneshot", "SU"],
    ["Lean Finance CFO", "cfo recurrente", "FI"],
    ["Gestión laboral", "asesoria recurrente", "LA"],
    # Sin departamento
    ["Prescripciones del Banco Sabadell", "partnerships recurrente", ""],
    # Solo nombre
    ["SaaS Growth", "partnerships oneshot", ""],
    ["Servicios DATA", "serviciosdata recurrente", "DA"],
]


# ── Tests de parsing de usuarios ─────────────────────────────────


class TestParseTeamMembers:
    def test_parse_all_valid_rows(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        assert len(members) == 6

    def test_skips_header(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        assert all(m.email != "hubspot_tec_id" for m in members)

    def test_basic_fields(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        candi = members[0]
        assert candi.hubspot_tec_id == "1404036103"
        assert candi.slack_id == "U02QKGE0QP6"
        assert candi.email == "candido@leanfinance.es"
        assert candi.nombre_completo == "Candi Diaz"
        assert candi.nombre_corto == "Candi"
        assert candi.department == Department.SU

    def test_responsable_true(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        jose_angel = members[1]
        assert jose_angel.is_responsable is True

    def test_responsable_false(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        candi = members[0]
        assert candi.is_responsable is False

    def test_empty_hubspot_id_becomes_none(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        abraham = [m for m in members if m.nombre_corto == "Abraham"][0]
        assert abraham.hubspot_tec_id is None

    def test_missing_responsable_column_defaults_false(self) -> None:
        members = _parse_team_members(USERS_ROWS)
        tech = [m for m in members if m.nombre_corto == "Tech Lean Finance"][0]
        assert tech.is_responsable is False

    def test_empty_rows_returns_empty(self) -> None:
        assert _parse_team_members([]) == []

    def test_only_header_returns_empty(self) -> None:
        assert _parse_team_members([USERS_ROWS[0]]) == []

    def test_row_too_short_is_skipped(self) -> None:
        rows = [
            USERS_ROWS[0],
            ["123", "UABC", "test@test.com"],  # Solo 3 columnas
        ]
        members = _parse_team_members(rows)
        assert len(members) == 0

    def test_unknown_department_is_skipped(self) -> None:
        rows = [
            USERS_ROWS[0],
            ["123", "UABC", "test@test.com", "Test User", "Test", "XX", "FALSE"],
        ]
        members = _parse_team_members(rows)
        assert len(members) == 0


# ── Tests de parsing de servicios ────────────────────────────────


class TestParseServices:
    def test_parse_all_rows(self) -> None:
        services = _parse_services(SERVICES_ROWS)
        assert len(services) == 7

    def test_skips_header(self) -> None:
        services = _parse_services(SERVICES_ROWS)
        assert all(s.nombre != "nombre" for s in services)

    def test_basic_fields(self) -> None:
        services = _parse_services(SERVICES_ROWS)
        enisa = [s for s in services if "ENISA" in s.nombre][0]
        assert enisa.nombre == "Préstamo ENISA"
        assert enisa.tags == "financiacionpublica oneshot"
        assert enisa.department == Department.SU

    def test_service_without_department(self) -> None:
        services = _parse_services(SERVICES_ROWS)
        sabadell = [s for s in services if "Sabadell" in s.nombre][0]
        assert sabadell.department is None

    def test_empty_rows_returns_empty(self) -> None:
        assert _parse_services([]) == []

    def test_all_departments_parsed(self) -> None:
        services = _parse_services(SERVICES_ROWS)
        departments = {s.department for s in services if s.department}
        assert Department.AS in departments
        assert Department.SU in departments
        assert Department.FI in departments
        assert Department.LA in departments
        assert Department.DA in departments
