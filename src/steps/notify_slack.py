"""Step: notificar al técnico por Slack (DM)."""

from __future__ import annotations

import structlog

from src.clients.slack import SlackClient
from src.models.enums import StepName
from src.steps.base import BaseStep, StepContext, StepResult

logger = structlog.get_logger()


class NotifySlackStep(BaseStep):
    """Envía un DM al técnico asignado notificándole del nuevo negocio."""

    def __init__(self, slack_client: SlackClient) -> None:
        self._slack = slack_client

    @property
    def name(self) -> StepName:
        return StepName.NOTIFY_SLACK

    async def execute(self, ctx: StepContext) -> StepResult:
        log = logger.bind(deal_id=ctx.deal_id, company=ctx.company_name)

        if not ctx.technician or not ctx.technician.slack_id:
            return StepResult(success=False, error="No hay slack_id del técnico")

        message = _build_message(ctx)

        ts = await self._slack.send_dm(
            user_id=ctx.technician.slack_id,
            text=message,
        )

        log.info(
            "slack_dm_sent_to_technician",
            technician=ctx.technician.nombre_corto,
            slack_id=ctx.technician.slack_id,
            ts=ts,
        )

        return StepResult(success=True, data={"slack_ts": ts})


def _build_message(ctx: StepContext) -> str:
    """Construye el mensaje de Slack para el técnico."""
    tech_name = ctx.technician.nombre_corto if ctx.technician else "técnico"
    return (
        f"Hola {tech_name} 👋\n\n"
        f"Se te ha asignado un nuevo negocio: *{ctx.deal_name}*\n"
        f"Empresa: *{ctx.company_name}*\n"
        f"Servicio: *{ctx.service_name}*\n\n"
        f"Revisa tu bandeja de entrada de email para más información."
    )
