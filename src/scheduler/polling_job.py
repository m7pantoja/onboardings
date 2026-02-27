"""Job de polling: detecta nuevos deals, reintenta pendientes, notifica errores al admin."""

from __future__ import annotations

import structlog

from src.clients.gmail import GmailClient
from src.models.deal import EnrichedDeal
from src.models.onboarding import OnboardingRecord
from src.persistence.repository import OnboardingRepository
from src.services.deal_detector import DealDetector
from src.services.onboarding_manager import OnboardingManager

logger = structlog.get_logger()


class PollingJob:
    """Ciclo de polling ejecutado periódicamente por APScheduler.

    Responsabilidades:
    1. Detectar nuevos deals WON en HubSpot y procesarlos.
    2. Reintentar onboardings pendientes/fallidos (re-enriqueciendo desde HubSpot).
    3. Notificar al admin por email si hay onboardings en FAILED tras el ciclo.
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
        """Ejecuta un ciclo completo de polling.

        Las excepciones no manejadas se propagan para que APScheduler
        dispare EVENT_JOB_ERROR y se notifique al admin.
        """
        log = logger.bind(job="polling")
        log.info("polling_cycle_started")

        await self._process_new_deals()
        await self._retry_pending_onboardings()
        await self._notify_failed_summary()

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

    async def _process_new_deals(self) -> None:
        """Detecta y procesa nuevos deals WON."""
        new_deals = await self._detector.detect_new_deals()
        logger.info("new_deals_detected", count=len(new_deals))

        for deal in new_deals:
            await self._safe_process_deal(deal, context="new_deal")

    async def _retry_pending_onboardings(self) -> None:
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
                continue

            if enriched is None:
                log.warning("deal_not_enrichable")
                continue

            await self._safe_process_deal(enriched, context="retry")

    async def _safe_process_deal(self, deal: EnrichedDeal, context: str) -> None:
        """Procesa un deal capturando errores para no interrumpir el ciclo."""
        log = logger.bind(deal_id=deal.deal_id, context=context)
        try:
            result = await self._manager.process_deal(deal)
            log.info("deal_processed", status=result.status.value)
        except Exception as exc:
            log.error("deal_processing_error", error=str(exc))

    async def _notify_failed_summary(self) -> None:
        """Envía resumen al admin si hay onboardings en FAILED."""
        failed = await self._repo.list_failed()
        if not failed:
            return

        logger.warning("failed_onboardings_exist", count=len(failed))

        lines = [f"Se encontraron {len(failed)} onboarding(s) con errores:\n"]
        for r in failed:
            lines.append(
                f"  • Deal {r.deal_id}: {r.deal_name} "
                f"(depto: {r.department or 'sin asignar'})"
            )

        body_text = "\n".join(lines)
        subject = f"[LeanFinance Onboardings] {len(failed)} onboarding(s) con error"

        try:
            await self._gmail.send_email(
                to=self._admin_email,
                subject=subject,
                body_html=f"<pre>{body_text}</pre>",
            )
            logger.info("admin_notified_failed_summary", count=len(failed))
        except Exception as exc:
            logger.error("failed_summary_email_error", error=str(exc))
