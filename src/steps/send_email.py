"""Step: enviar email al técnico con información del onboarding."""

from __future__ import annotations

import structlog

from src.clients.gmail import GmailClient
from src.models.enums import StepName
from src.models.sheets import DEPARTMENT_LABELS
from src.steps.base import BaseStep, StepContext, StepResult

logger = structlog.get_logger()


class SendEmailStep(BaseStep):
    """Envía email al técnico con enlaces a Drive, Holded y HubSpot."""

    def __init__(self, gmail_client: GmailClient) -> None:
        self._gmail = gmail_client

    @property
    def name(self) -> StepName:
        return StepName.SEND_EMAIL

    async def execute(self, ctx: StepContext) -> StepResult:
        log = logger.bind(deal_id=ctx.deal_id, company=ctx.company_name)

        if not ctx.technician:
            return StepResult(success=False, error="No hay técnico asignado")

        subject = f"Nuevo onboarding: {ctx.company_name} — {ctx.service_name}"
        body_html = _build_email_html(ctx)

        message_id = await self._gmail.send_email(
            to=ctx.technician.email,
            subject=subject,
            body_html=body_html,
        )

        log.info(
            "email_sent_to_technician",
            technician=ctx.technician.nombre_corto,
            email=ctx.technician.email,
            message_id=message_id,
        )

        return StepResult(success=True, data={"gmail_message_id": message_id})


def _build_email_html(ctx: StepContext) -> str:
    """Construye el cuerpo HTML del email de onboarding."""
    tech_name = ctx.technician.nombre_corto if ctx.technician else "técnico"
    dept_label = ""
    if ctx.department:
        dept_label = DEPARTMENT_LABELS.get(ctx.department, ctx.department.value)

    # Enlaces
    links_html = ""
    if ctx.drive_folder_url:
        links_html += f'<li><strong>Google Drive:</strong> <a href="{ctx.drive_folder_url}">Carpeta del cliente</a></li>\n'
    if ctx.holded_contact_url:
        links_html += f'<li><strong>Holded:</strong> <a href="{ctx.holded_contact_url}">Ficha del contacto</a></li>\n'
    if ctx.hubspot_deal_url:
        links_html += f'<li><strong>HubSpot:</strong> <a href="{ctx.hubspot_deal_url}">Deal en HubSpot</a></li>\n'

    return f"""\
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2>Nuevo onboarding asignado</h2>

    <p>Hola {tech_name},</p>

    <p>Se te ha asignado un nuevo negocio. A continuación tienes los detalles:</p>

    <table style="border-collapse: collapse; width: 100%; margin: 16px 0;">
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Negocio</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{ctx.deal_name}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Empresa</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{ctx.company_name}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Servicio</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{ctx.service_name}</td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">Departamento</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{dept_label}</td>
        </tr>
    </table>

    <h3>Enlaces</h3>
    <ul>
        {links_html}
    </ul>

    <div style="background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 12px; margin: 16px 0;">
        <strong>⚠️ Importante:</strong> La ficha del cliente en Holded se ha creado automáticamente
        y <strong>no ha sido supervisada</strong>. Por favor, revisa que los datos sean correctos
        antes de empezar a trabajar.
    </div>

    <p style="color: #666; font-size: 12px; margin-top: 24px;">
        Este email ha sido enviado automáticamente por el sistema de onboardings de LeanFinance.
    </p>
</div>
"""
