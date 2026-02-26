"""Cliente async para leer la Google Sheet 'matriz-onboardings'."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from src.clients.google_auth import get_google_credentials
from src.models.sheets import Department, ServiceEntry, TeamMember

logger = structlog.get_logger()

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Rangos de las hojas (todas las columnas con datos)
USERS_RANGE = "usuarios!A:G"
SERVICES_RANGE = "servicios!A:C"


class GoogleSheetsError(Exception):
    """Error al comunicarse con la Google Sheets API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleSheetsClient:
    """Cliente async para leer datos de la Google Sheet de onboardings.

    Cachea los resultados en memoria durante `cache_ttl_seconds` para evitar
    peticiones innecesarias (la Sheet no cambia frecuentemente).

    Uso como context manager async:
        async with GoogleSheetsClient(spreadsheet_id="...") as client:
            members = await client.fetch_team_members()
            services = await client.fetch_services()
    """

    def __init__(
        self,
        spreadsheet_id: str,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._cache_ttl = cache_ttl_seconds
        self._client: httpx.AsyncClient | None = None

        # Cache
        self._members_cache: list[TeamMember] | None = None
        self._members_cached_at: float = 0.0
        self._services_cache: list[ServiceEntry] | None = None
        self._services_cached_at: float = 0.0

    async def __aenter__(self) -> GoogleSheetsClient:
        creds = get_google_credentials()
        self._client = httpx.AsyncClient(
            base_url=SHEETS_API_BASE,
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    # ── Métodos públicos ────────────────────────────────────────

    async def fetch_team_members(self) -> list[TeamMember]:
        """Lee la hoja 'usuarios' y devuelve la lista de miembros del equipo."""
        now = time.monotonic()
        if self._members_cache is not None and (now - self._members_cached_at) < self._cache_ttl:
            return self._members_cache

        rows = await self._read_range(USERS_RANGE)
        members = _parse_team_members(rows)

        self._members_cache = members
        self._members_cached_at = now
        logger.info("sheets_team_members_loaded", count=len(members))
        return members

    async def fetch_services(self) -> list[ServiceEntry]:
        """Lee la hoja 'servicios' y devuelve la lista de servicios."""
        now = time.monotonic()
        if self._services_cache is not None and (now - self._services_cached_at) < self._cache_ttl:
            return self._services_cache

        rows = await self._read_range(SERVICES_RANGE)
        services = _parse_services(rows)

        self._services_cache = services
        self._services_cached_at = now
        logger.info("sheets_services_loaded", count=len(services))
        return services

    def invalidate_cache(self) -> None:
        """Fuerza la recarga en la próxima petición."""
        self._members_cache = None
        self._services_cache = None

    # ── Internals ───────────────────────────────────────────────

    async def _read_range(self, range_: str) -> list[list[str]]:
        """Lee un rango de la spreadsheet y devuelve las filas como listas de strings."""
        assert self._client is not None, "Usar como context manager: async with GoogleSheetsClient(...)"

        url = f"/{self._spreadsheet_id}/values/{range_}"
        response = await self._client.get(url)

        if response.status_code >= 400:
            raise GoogleSheetsError(
                f"Google Sheets {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        data: dict[str, Any] = response.json()
        return data.get("values", [])


# ── Parsing ─────────────────────────────────────────────────────


def _parse_team_members(rows: list[list[str]]) -> list[TeamMember]:
    """Parsea las filas de la hoja 'usuarios' (sin la cabecera)."""
    if not rows:
        return []

    # Primera fila = cabecera, la saltamos
    members: list[TeamMember] = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < 6:
            logger.warning("sheets_users_row_too_short", row_number=i, columns=len(row))
            continue

        dept_code = row[5].strip().upper()
        try:
            department = Department(dept_code)
        except ValueError:
            logger.warning("sheets_users_unknown_department", row_number=i, department=dept_code)
            continue

        # Columna G (responsable) es un checkbox: TRUE/FALSE o vacío
        is_responsable = len(row) >= 7 and row[6].strip().upper() == "TRUE"

        members.append(
            TeamMember(
                hubspot_tec_id=row[0].strip() or None,
                slack_id=row[1].strip() or None,
                email=row[2].strip(),
                nombre_completo=row[3].strip(),
                nombre_corto=row[4].strip(),
                department=department,
                is_responsable=is_responsable,
            )
        )

    return members


def _parse_services(rows: list[list[str]]) -> list[ServiceEntry]:
    """Parsea las filas de la hoja 'servicios' (sin la cabecera)."""
    if not rows:
        return []

    services: list[ServiceEntry] = []
    for i, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            continue

        nombre = row[0].strip()
        tags = row[1].strip() if len(row) > 1 and row[1].strip() else None

        department: Department | None = None
        if len(row) > 2 and row[2].strip():
            dept_code = row[2].strip().upper()
            try:
                department = Department(dept_code)
            except ValueError:
                logger.warning(
                    "sheets_services_unknown_department",
                    row_number=i,
                    service=nombre,
                    department=dept_code,
                )

        services.append(ServiceEntry(nombre=nombre, tags=tags, department=department))

    return services
