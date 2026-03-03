"""Step: crear carpeta de cliente en Google Drive (+ subcarpeta por departamento)."""

from __future__ import annotations

import structlog

from src.clients.google_drive import GoogleDriveClient, folder_url
from src.models.enums import StepName
from src.models.sheets import DEPARTMENT_DRIVE_SUBFOLDER
from src.steps.base import BaseStep, StepContext, StepResult

logger = structlog.get_logger()

# ID de la carpeta padre en el Shared Drive
PARENT_FOLDER_ID = "0AN-sodeoSVkMUk9PVA"


class CreateDriveFolderStep(BaseStep):
    """Crea carpeta de cliente en Drive y subcarpeta por departamento si aplica.

    Idempotencia:
    - La carpeta se busca por nombre en Drive antes de crearla (find_or_create_folder).
    - La subcarpeta también se busca por nombre dentro de la carpeta del cliente.
    - En reintentos, el engine salta el step automáticamente si ya está COMPLETED en BD.
    """

    def __init__(self, drive_client: GoogleDriveClient) -> None:
        self._drive = drive_client

    @property
    def name(self) -> StepName:
        return StepName.CREATE_DRIVE_FOLDER

    async def execute(self, ctx: StepContext) -> StepResult:
        log = logger.bind(deal_id=ctx.deal_id, company=ctx.company_name)

        # 1. Crear o reutilizar carpeta del cliente (idempotente vía Drive)
        client_folder_id = await self._drive.find_or_create_folder(
            ctx.company_name, parent_id=PARENT_FOLDER_ID
        )
        log.info("drive_client_folder_ready", folder_id=client_folder_id)

        ctx.drive_folder_id = client_folder_id
        ctx.drive_folder_url = folder_url(client_folder_id)

        # 2. Crear subcarpeta si el departamento lo requiere
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
