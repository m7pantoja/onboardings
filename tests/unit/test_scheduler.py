"""Tests para PollingJob."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.deal import CompanyInfo, ContactPersonInfo, EnrichedDeal
from src.models.enums import OnboardingStatus
from src.models.onboarding import OnboardingRecord
from src.scheduler.polling_job import PollingJob


# ── Helpers ──────────────────────────────────────────────────────


def _make_enriched_deal(deal_id: int = 100) -> EnrichedDeal:
    return EnrichedDeal(
        deal_id=deal_id,
        deal_name=f"ACME SL - CFO",
        company_name="ACME SL",
        service_name="CFO",
        close_date=datetime(2025, 6, 1),
        hubspot_owner_id=111,
        company=CompanyInfo(company_id="500", name="ACME SL"),
        contact_person=ContactPersonInfo(contact_id="600"),
        technicians=[],
    )


def _make_record(
    deal_id: int = 100,
    status: OnboardingStatus = OnboardingStatus.PENDING,
) -> OnboardingRecord:
    return OnboardingRecord(
        id=1,
        deal_id=deal_id,
        deal_name="ACME SL - CFO",
        company_name="ACME SL",
        service_name="CFO",
        department="FI",
        hubspot_owner_id=111,
        status=status,
    )


@pytest.fixture
def polling_job() -> PollingJob:
    """Crea un PollingJob con todas las dependencias mockeadas."""
    detector = AsyncMock()
    detector.detect_new_deals.return_value = []
    detector.enrich_deal_by_id.return_value = None

    manager = AsyncMock()
    manager.process_deal.return_value = _make_record(status=OnboardingStatus.COMPLETED)

    repo = AsyncMock()
    repo.list_pending.return_value = []
    repo.list_failed.return_value = []

    gmail = AsyncMock()

    job = PollingJob(
        detector=detector,
        manager=manager,
        repository=repo,
        gmail_client=gmail,
        admin_email="admin@test.com",
    )
    return job


# ── Tests del ciclo run() ────────────────────────────────────────


class TestPollingJobRun:
    async def test_ciclo_vacio_sin_errores(self, polling_job: PollingJob):
        """Sin nuevos deals ni pendientes, completa sin enviar emails."""
        await polling_job.run()

        polling_job._detector.detect_new_deals.assert_awaited_once()
        polling_job._repo.list_pending.assert_awaited_once()
        polling_job._repo.list_failed.assert_awaited_once()
        polling_job._gmail.send_email.assert_not_awaited()

    async def test_procesa_nuevos_deals(self, polling_job: PollingJob):
        deal1 = _make_enriched_deal(100)
        deal2 = _make_enriched_deal(200)
        polling_job._detector.detect_new_deals.return_value = [deal1, deal2]

        await polling_job.run()

        assert polling_job._manager.process_deal.await_count == 2
        polling_job._manager.process_deal.assert_any_await(deal1)
        polling_job._manager.process_deal.assert_any_await(deal2)

    async def test_error_en_un_deal_no_interrumpe_ciclo(self, polling_job: PollingJob):
        """Si process_deal falla en un deal, el siguiente se procesa."""
        deal1 = _make_enriched_deal(100)
        deal2 = _make_enriched_deal(200)
        polling_job._detector.detect_new_deals.return_value = [deal1, deal2]

        polling_job._manager.process_deal.side_effect = [
            RuntimeError("boom"),
            _make_record(deal_id=200, status=OnboardingStatus.COMPLETED),
        ]

        await polling_job.run()

        assert polling_job._manager.process_deal.await_count == 2

    async def test_reintenta_pendientes(self, polling_job: PollingJob):
        record = _make_record(deal_id=100, status=OnboardingStatus.WAITING_TECHNICIAN)
        polling_job._repo.list_pending.return_value = [record]

        enriched = _make_enriched_deal(100)
        polling_job._detector.enrich_deal_by_id.return_value = enriched

        await polling_job.run()

        polling_job._detector.enrich_deal_by_id.assert_awaited_once_with(100)
        polling_job._manager.process_deal.assert_awaited_once_with(enriched)

    async def test_enrich_falla_salta_ese_pendiente(self, polling_job: PollingJob):
        """Si enrich_deal_by_id falla, ese record se salta sin crashear."""
        record = _make_record(deal_id=100)
        polling_job._repo.list_pending.return_value = [record]
        polling_job._detector.enrich_deal_by_id.side_effect = RuntimeError("HubSpot error")

        await polling_job.run()

        polling_job._manager.process_deal.assert_not_awaited()

    async def test_enrich_devuelve_none_salta(self, polling_job: PollingJob):
        """Si enrich_deal_by_id devuelve None, ese record se salta."""
        record = _make_record(deal_id=100)
        polling_job._repo.list_pending.return_value = [record]
        polling_job._detector.enrich_deal_by_id.return_value = None

        await polling_job.run()

        polling_job._manager.process_deal.assert_not_awaited()


# ── Tests de notificaciones ──────────────────────────────────────


class TestPollingJobNotifications:
    async def test_notifica_admin_con_failed_al_final(self, polling_job: PollingJob):
        failed1 = _make_record(deal_id=100, status=OnboardingStatus.FAILED)
        failed2 = _make_record(deal_id=200, status=OnboardingStatus.FAILED)
        polling_job._repo.list_failed.return_value = [failed1, failed2]

        await polling_job.run()

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert call_kwargs["to"] == "admin@test.com"
        assert "2 onboarding(s) con error" in call_kwargs["subject"]

    async def test_no_notifica_si_no_hay_failed(self, polling_job: PollingJob):
        polling_job._repo.list_failed.return_value = []

        await polling_job.run()

        polling_job._gmail.send_email.assert_not_awaited()

    async def test_email_error_no_crashea(self, polling_job: PollingJob):
        """Si el email de resumen falla, el ciclo no crashea."""
        polling_job._repo.list_failed.return_value = [
            _make_record(status=OnboardingStatus.FAILED),
        ]
        polling_job._gmail.send_email.side_effect = RuntimeError("SMTP error")

        await polling_job.run()  # No debe lanzar excepción


class TestNotifyCriticalError:
    async def test_envia_email_al_admin(self, polling_job: PollingJob):
        error = ValueError("algo salió mal")
        await polling_job.notify_critical_error(error, "Traceback...")

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert call_kwargs["to"] == "admin@test.com"
        assert "ERROR CRITICO" in call_kwargs["subject"]
        assert "ValueError" in call_kwargs["body_html"]
        assert "Traceback..." in call_kwargs["body_html"]

    async def test_email_falla_no_lanza_excepcion(self, polling_job: PollingJob):
        polling_job._gmail.send_email.side_effect = RuntimeError("SMTP error")

        await polling_job.notify_critical_error(ValueError("boom"))
        # No debe lanzar excepción
