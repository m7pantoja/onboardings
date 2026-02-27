"""Step: crear carpeta de cliente en Google Drive (+ subcarpeta por departamento)."""

from __future__ import annotations

import structlog

from src.clients.google_drive import GoogleDriveClient, folder_url
from src.clients.hubspot import HubSpotClient
from src.models.enums import StepName
from src.models.sheets import DEPARTMENT_DRIVE_SUBFOLDER
from src.steps.base import BaseStep, StepContext, StepResult

logger = structlog.get_logger()

# ID de la carpeta padre en el Shared Drive
PARENT_FOLDER_ID = "0AN-sodeoSVkMUk9PVA"


class CreateDriveFolderStep(BaseStep):
    """Crea carpeta de cliente en Drive y subcarpeta por departamento si aplica.

    Idempotencia:
    - Carpeta de cliente: se verifica via `drive_folder_id` en HubSpot Company.
      Si ya existe, se reutiliza.
    - Subcarpeta: se busca por nombre dentro de la carpeta del cliente.
      Si ya existe, no se crea de nuevo.

    Tras crear, escribe `drive_folder_id` y `drive_folder_url` en HubSpot Company.
    """

    def __init__(self, drive_client: GoogleDriveClient, hubspot_client: HubSpotClient) -> None:
        self._drive = drive_client
        self._hubspot = hubspot_client

    @property
    def name(self) -> StepName:
        return StepName.CREATE_DRIVE_FOLDER

    async def check_already_done(self, ctx: StepContext) -> bool:
        """Si ya tiene drive_folder_id Y no necesita subcarpeta (o ya la tiene), skip."""
        if not ctx.company or not ctx.company.drive_folder_id:
            return False

        # Carpeta del cliente existe. ¿Necesita subcarpeta?
        if ctx.department and ctx.department in DEPARTMENT_DRIVE_SUBFOLDER:
            # Verificar si la subcarpeta ya existe
            subfolder_name = DEPARTMENT_DRIVE_SUBFOLDER[ctx.department]
            existing = await self._drive.find_folder(subfolder_name, ctx.company.drive_folder_id)
            if existing:
                # Todo ya existe
                ctx.drive_folder_id = ctx.company.drive_folder_id
                ctx.drive_folder_url = ctx.company.drive_folder_url
                ctx.drive_subfolder_id = existing
                return True

            # Carpeta existe pero falta subcarpeta → no skip
            return False

        # No necesita subcarpeta y ya tiene folder → skip
        ctx.drive_folder_id = ctx.company.drive_folder_id
        ctx.drive_folder_url = ctx.company.drive_folder_url
        return True

    async def execute(self, ctx: StepContext) -> StepResult:
        log = logger.bind(deal_id=ctx.deal_id, company=ctx.company_name)

        # 1. Crear o reutilizar carpeta del cliente
        if ctx.company and ctx.company.drive_folder_id:
            client_folder_id = ctx.company.drive_folder_id
            log.info("drive_client_folder_exists", folder_id=client_folder_id)
        else:
            client_folder_id = await self._drive.find_or_create_folder(
                ctx.company_name, parent_id=PARENT_FOLDER_ID
            )
            log.info("drive_client_folder_ready", folder_id=client_folder_id)

        ctx.drive_folder_id = client_folder_id
        ctx.drive_folder_url = folder_url(client_folder_id)

        # 2. Write-back a HubSpot Company
        if ctx.company and not ctx.company.drive_folder_id:
            await self._hubspot.update_company(
                ctx.company.company_id,
                {
                    "drive_folder_id": client_folder_id,
                    "drive_folder_url": ctx.drive_folder_url,
                },
            )
            log.info("hubspot_drive_ids_written", company_id=ctx.company.company_id)

        # 3. Crear subcarpeta si el departamento lo requiere
        subfolder_id: str | None = None
        if ctx.department and ctx.department in DEPARTMENT_DRIVE_SUBFOLDER:
            subfolder_name = DEPARTMENT_DRIVE_SUBFOLDER[ctx.department]
            subfolder_id = await self._drive.find_or_create_folder(
                subfolder_name, parent_id=client_folder_id
            )
            ctx.drive_subfolder_id = subfolder_id
            log.info("drive_subfolder_ready", subfolder_name=subfolder_name, subfolder_id=subfolder_id)

        return StepResult(
            success=True,
            data={
                "drive_folder_id": client_folder_id,
                "drive_folder_url": ctx.drive_folder_url,
                "drive_subfolder_id": subfolder_id,
            },
        )
