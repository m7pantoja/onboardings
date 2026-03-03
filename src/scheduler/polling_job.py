"""Job de polling: detecta nuevos deals, reintenta pendientes, notifica al admin."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog

from src.clients.gmail import GmailClient
from src.models.deal import EnrichedDeal
from src.models.enums import OnboardingStatus, StepName, StepStatus
from src.models.onboarding import OnboardingRecord, StepRecord
from src.persistence.repository import OnboardingRepository
from src.services.deal_detector import DealDetector
from src.services.onboarding_manager import OnboardingManager

logger = structlog.get_logger()


@dataclass
class DealResult:
    """Resultado del procesamiento de un deal durante el ciclo."""

    deal_id: int
    deal_name: str
    company_name: str
    context: str  # "new_deal" o "retry"
    record: OnboardingRecord | None = None
    error: str | None = None


@dataclass
class CycleReport:
    """Resumen acumulado de un ciclo de polling."""

    completed: list[DealResult] = field(default_factory=list)
    failed: list[DealResult] = field(default_factory=list)
    waiting: list[DealResult] = field(default_factory=list)
    errors: list[DealResult] = field(default_factory=list)  # Excepciones no controladas

    @property
    def has_activity(self) -> bool:
        return bool(self.completed or self.failed or self.waiting or self.errors)


class PollingJob:
    """Ciclo de polling ejecutado periódicamente por APScheduler.

    Responsabilidades:
    1. Detectar nuevos deals WON en HubSpot y procesarlos.
    2. Reintentar onboardings pendientes/fallidos (re-enriqueciendo desde HubSpot).
    3. Enviar email de reporte al admin con el resumen completo del ciclo.
    """

    def __init__(
        self,
        detector: DealDetector,
        manager: OnboardingManager,
        repository: OnboardingRepository,
        gmail_client: GmailClient,
        admin_email: str,
    ) -> None:
        self._detector = detector
        self._manager = manager
        self._repo = repository
        self._gmail = gmail_client
        self._admin_email = admin_email

    async def run(self) -> None:
        """Ejecuta un ciclo completo de polling."""
        log = logger.bind(job="polling")
        log.info("polling_cycle_started")

        report = CycleReport()

        await self._process_new_deals(report)
        await self._retry_pending_onboardings(report)
        await self._send_cycle_report(report)

        log.info("polling_cycle_completed")

    async def notify_critical_error(
        self,
        exception: BaseException,
        traceback_str: str | None = None,
    ) -> None:
        """Envía email al admin cuando el job falla con una excepción no controlada."""
        subject = "[LeanFinance Onboardings] ERROR CRITICO en polling"
        body = (
            "<h2>El job de polling ha fallado con una excepción no controlada.</h2>"
            f"<p><strong>Error:</strong> {type(exception).__name__}: {exception}</p>"
            f"<pre>{traceback_str or 'Sin traceback'}</pre>"
        )
        try:
            await self._gmail.send_email(
                to=self._admin_email,
                subject=subject,
                body_html=body,
            )
            logger.info("admin_notified_critical_error")
        except Exception as exc:
            logger.critical("admin_notification_failed", error=str(exc))

    # ── Internals ───────────────────────────────────────────────

    async def _process_new_deals(self, report: CycleReport) -> None:
        """Detecta y procesa nuevos deals WON."""
        new_deals = await self._detector.detect_new_deals()
        logger.info("new_deals_detected", count=len(new_deals))

        for deal in new_deals:
            await self._safe_process_deal(deal, context="new_deal", report=report)

    async def _retry_pending_onboardings(self, report: CycleReport) -> None:
        """Re-intenta onboardings pendientes re-enriqueciéndolos desde HubSpot."""
        pending = await self._repo.list_pending()
        if not pending:
            return

        logger.info("pending_onboardings_found", count=len(pending))

        for record in pending:
            log = logger.bind(onboarding_id=record.id, deal_id=record.deal_id)
            try:
                enriched = await self._detector.enrich_deal_by_id(record.deal_id)
            except Exception as exc:
                log.error("reenrich_failed", error=str(exc))
                report.errors.append(DealResult(
                    deal_id=record.deal_id,
                    deal_name=record.deal_name,
                    company_name=record.company_name,
                    context="retry",
                    error=f"Error al re-enriquecer desde HubSpot: {exc}",
                ))
                continue

            if enriched is None:
                log.warning("deal_not_enrichable")
                continue

            await self._safe_process_deal(enriched, context="retry", report=report)

    async def _safe_process_deal(
        self, deal: EnrichedDeal, context: str, report: CycleReport
    ) -> None:
        """Procesa un deal capturando errores para no interrumpir el ciclo."""
        log = logger.bind(deal_id=deal.deal_id, context=context)
        result = DealResult(
            deal_id=deal.deal_id,
            deal_name=deal.deal_name,
            company_name=deal.company_name,
            context=context,
        )

        try:
            record = await self._manager.process_deal(deal)
            result.record = record
            log.info("deal_processed", status=record.status.value)

            if record.status == OnboardingStatus.COMPLETED:
                report.completed.append(result)
            elif record.status == OnboardingStatus.WAITING_TECHNICIAN:
                report.waiting.append(result)
            elif record.status == OnboardingStatus.FAILED:
                report.failed.append(result)

        except Exception as exc:
            log.error("deal_processing_error", error=str(exc))
            result.error = str(exc)
            report.errors.append(result)

    async def _send_cycle_report(self, report: CycleReport) -> None:
        """Envía email al admin con el resumen completo del ciclo."""
        # Consultar failed acumulados en BD (incluye los de ciclos anteriores)
        all_failed_records = await self._repo.list_failed()

        if not report.has_activity and not all_failed_records:
            logger.info("cycle_report_skipped_no_activity")
            return

        subject = self._build_subject(report, len(all_failed_records))
        body_html = self._build_report_html(report, all_failed_records)

        try:
            await self._gmail.send_email(
                to=self._admin_email,
                subject=subject,
                body_html=body_html,
            )
            logger.info("cycle_report_sent")
        except Exception as exc:
            logger.error("cycle_report_email_error", error=str(exc))

    def _build_subject(self, report: CycleReport, total_failed: int) -> str:
        parts: list[str] = []
        if report.completed:
            parts.append(f"{len(report.completed)} completado(s)")
        if report.failed or report.errors:
            parts.append(f"{len(report.failed) + len(report.errors)} con error")
        if report.waiting:
            parts.append(f"{len(report.waiting)} esperando técnico")

        if parts:
            summary = ", ".join(parts)
        elif total_failed:
            summary = f"{total_failed} pendiente(s) de resolver"
        else:
            summary = "sin actividad"

        return f"[LeanFinance Onboardings] Reporte: {summary}"

    def _build_report_html(
        self, report: CycleReport, all_failed_records: list[OnboardingRecord]
    ) -> str:
        sections: list[str] = []

        # Completados en este ciclo
        if report.completed:
            items = []
            for r in report.completed:
                context_label = "nuevo" if r.context == "new_deal" else "reintento"
                steps_html = self._format_steps_detail(r.record) if r.record else ""
                items.append(
                    f"<div style='margin-bottom: 16px; padding: 12px; background: #f0fff0; border-left: 4px solid #28a745;'>"
                    f"<strong>{r.deal_name}</strong> <span style='color: #666;'>({context_label})</span><br>"
                    f"<span style='color: #555;'>Empresa: {r.company_name}</span>"
                    f"{steps_html}"
                    f"</div>"
                )
            sections.append(
                f"<h2 style='color: #28a745;'>✅ Completados ({len(report.completed)})</h2>"
                + "".join(items)
            )

        # Esperando técnico
        if report.waiting:
            items = []
            for r in report.waiting:
                dept = r.record.department if r.record else "-"
                items.append(
                    f"<div style='margin-bottom: 8px; padding: 12px; background: #fffbf0; border-left: 4px solid #ffc107;'>"
                    f"<strong>{r.deal_name}</strong><br>"
                    f"Empresa: {r.company_name} · Departamento: {dept}<br>"
                    f"<span style='color: #856404;'>Se ha notificado al responsable del departamento por Slack.</span>"
                    f"</div>"
                )
            sections.append(
                f"<h2 style='color: #ffc107;'>⏳ Esperando técnico ({len(report.waiting)})</h2>"
                + "".join(items)
            )

        # Errores en este ciclo (fallos del pipeline + excepciones)
        cycle_errors = report.failed + report.errors
        if cycle_errors:
            items = []
            for r in cycle_errors:
                context_label = "nuevo" if r.context == "new_deal" else "reintento"
                error_html = self._format_deal_error_detail(r)
                items.append(
                    f"<div style='margin-bottom: 16px; padding: 12px; background: #fff5f5; border-left: 4px solid #dc3545;'>"
                    f"<strong>{r.deal_name}</strong> <span style='color: #666;'>({context_label})</span><br>"
                    f"<span style='color: #555;'>Empresa: {r.company_name}</span>"
                    f"{error_html}"
                    f"</div>"
                )
            sections.append(
                f"<h2 style='color: #dc3545;'>❌ Errores en este ciclo ({len(cycle_errors)})</h2>"
                + "".join(items)
            )

        # Failed acumulados en BD
        if all_failed_records:
            items = []
            for rec in all_failed_records:
                steps_html = self._format_steps_detail(rec)
                items.append(
                    f"<div style='margin-bottom: 16px; padding: 12px; background: #fff5f5; border-left: 4px solid #dc3545;'>"
                    f"<strong>{rec.deal_name}</strong><br>"
                    f"<span style='color: #555;'>Empresa: {rec.company_name} · Departamento: {rec.department or 'sin asignar'}</span>"
                    f"{steps_html}"
                    f"</div>"
                )
            sections.append(
                f"<h2 style='color: #dc3545;'>📋 Total con errores en BD ({len(all_failed_records)})</h2>"
                f"<p style='color: #666;'>Incluye errores de ciclos anteriores no resueltos.</p>"
                + "".join(items)
            )

        if not sections:
            sections.append("<p>Ciclo completado sin actividad.</p>")

        return (
            "<div style='font-family: Arial, sans-serif; max-width: 800px;'>"
            "<h1>Reporte de Onboardings</h1>"
            + "".join(sections)
            + "<hr><p style='color: #999; font-size: 12px;'>Generado automáticamente por el sistema de onboardings.</p>"
            "</div>"
        )

    # ── Formateo de steps y errores ──────────────────────────────

    STEP_LABELS: dict[str, str] = {
        StepName.CREATE_DRIVE_FOLDER: "Carpeta Drive",
        StepName.CREATE_HOLDED_CONTACT: "Contacto Holded",
        StepName.NOTIFY_SLACK: "Notificación Slack",
        StepName.SEND_EMAIL: "Email al técnico",
        StepName.NOTIFY_MANAGER: "Notificación al responsable",
    }

    def _step_label(self, step_name: str) -> str:
        return self.STEP_LABELS.get(step_name, step_name)

    def _format_steps_detail(self, record: OnboardingRecord) -> str:
        """Formatea todos los steps de un onboarding (completados, saltados y fallidos)."""
        if not record.steps:
            return ""

        lines: list[str] = []
        for step in record.steps:
            label = self._step_label(step.step_name.value)
            if step.status == StepStatus.COMPLETED:
                detail = self._step_completed_detail(step)
                lines.append(f"✅ {label}{detail}")
            elif step.status == StepStatus.SKIPPED:
                lines.append(f"⏭️ {label} — ya existía, no se modificó")
            elif step.status == StepStatus.FAILED:
                error = _clean_error_message(step.error_message or "sin detalle")
                lines.append(f"❌ {label} — {error}")

        if not lines:
            return ""
        return "<ul style='margin: 8px 0 0 0; padding-left: 20px;'>" + "".join(
            f"<li>{line}</li>" for line in lines
        ) + "</ul>"

    def _step_completed_detail(self, step: StepRecord) -> str:
        """Genera el detalle de un step completado con datos relevantes."""
        data = step.result_data or {}

        if step.step_name == StepName.CREATE_DRIVE_FOLDER:
            url = data.get("drive_folder_url", "")
            if url:
                return f" — <a href='{url}'>ver carpeta</a>"
            return " — carpeta creada"

        if step.step_name == StepName.CREATE_HOLDED_CONTACT:
            url = data.get("holded_contact_url", "")
            if url:
                return f" — <a href='{url}'>ver contacto</a>"
            contact_id = data.get("holded_contact_id", "")
            if contact_id:
                return f" — ID: {contact_id}"
            return " — contacto creado"

        if step.step_name == StepName.NOTIFY_SLACK:
            return " — mensaje enviado"

        if step.step_name == StepName.SEND_EMAIL:
            return " — email enviado"

        return ""

    def _format_deal_error_detail(self, result: DealResult) -> str:
        """Formatea el detalle de un deal con error, mostrando steps OK y fallidos."""
        parts: list[str] = []

        # Error a nivel de excepción (no llegó al pipeline)
        if result.error:
            clean = _clean_error_message(result.error)
            parts.append(f"<li style='color: #dc3545;'>❌ {clean}</li>")

        # Steps del record (puede tener algunos OK y otros fallidos)
        if result.record and result.record.steps:
            for step in result.record.steps:
                label = self._step_label(step.step_name.value)
                if step.status == StepStatus.COMPLETED:
                    detail = self._step_completed_detail(step)
                    parts.append(f"<li>✅ {label}{detail}</li>")
                elif step.status == StepStatus.SKIPPED:
                    parts.append(f"<li>⏭️ {label} — ya existía</li>")
                elif step.status == StepStatus.FAILED:
                    error = _clean_error_message(step.error_message or "sin detalle")
                    parts.append(f"<li style='color: #dc3545;'>❌ {label} — {error}</li>")

        if not parts:
            parts.append("<li style='color: #dc3545;'>❌ Error desconocido</li>")

        return "<ul style='margin: 8px 0 0 0; padding-left: 20px;'>" + "".join(parts) + "</ul>"


def _clean_error_message(raw: str) -> str:
    """Limpia mensajes de error de APIs para hacerlos legibles.

    - Parsea JSON de HubSpot/Holded para extraer solo el mensaje y categoría.
    - Elimina URLs largas y correlation IDs.
    - Trunca mensajes excesivamente largos.
    """
    # Intentar extraer JSON de un mensaje tipo "HubSpot 403: {json...}"
    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            parts = []
            # Mensaje principal
            if "message" in data:
                parts.append(data["message"])
            # Categoría (ej: MISSING_SCOPES)
            if "category" in data:
                parts.append(f"({data['category']})")
            # Scopes requeridos
            if "errors" in data:
                for err in data["errors"]:
                    ctx = err.get("context", {})
                    scopes = ctx.get("requiredGranularScopes", [])
                    if scopes:
                        parts.append(f"Scopes necesarios: {', '.join(scopes)}")
            if parts:
                # Prefijo con código HTTP si está presente
                http_prefix = raw[:json_match.start()].strip().rstrip(":")
                if http_prefix:
                    return f"{http_prefix}: {' '.join(parts)}"
                return " ".join(parts)
        except (json.JSONDecodeError, KeyError):
            pass

    # Limpiar prefijo "Excepción no controlada: "
    cleaned = re.sub(r'^Excepción no controlada:\s*', '', raw)

    # Truncar si es muy largo
    if len(cleaned) > 200:
        return cleaned[:200] + "..."

    return cleaned
