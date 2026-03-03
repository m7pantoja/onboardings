"""Tests para PollingJob."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.models.deal import CompanyInfo, ContactPersonInfo, EnrichedDeal
from src.models.enums import OnboardingStatus, StepName, StepStatus
from src.models.onboarding import OnboardingRecord, StepRecord
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


def _make_failed_record_with_steps(deal_id: int = 100) -> OnboardingRecord:
    """Record con steps para simular list_failed() con detalle."""
    record = _make_record(deal_id=deal_id, status=OnboardingStatus.FAILED)
    record.steps = [
        StepRecord(
            onboarding_id=1,
            step_name=StepName.CREATE_DRIVE_FOLDER,
            status=StepStatus.COMPLETED,
            result_data={"folder_url": "https://drive.google.com/folders/123"},
        ),
        StepRecord(
            onboarding_id=1,
            step_name=StepName.CREATE_HOLDED_CONTACT,
            status=StepStatus.FAILED,
            error_message="Holded API 500: Internal Server Error",
        ),
    ]
    return record


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
        """Sin nuevos deals ni pendientes ni failed, no envía email."""
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


# ── Tests del reporte por email ──────────────────────────────────


class TestCycleReport:
    async def test_envia_reporte_con_completados(self, polling_job: PollingJob):
        """Cuando hay deals completados, envía reporte con detalle."""
        deal = _make_enriched_deal(100)
        polling_job._detector.detect_new_deals.return_value = [deal]

        await polling_job.run()

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert call_kwargs["to"] == "admin@test.com"
        assert "1 completado(s)" in call_kwargs["subject"]
        assert "Completados" in call_kwargs["body_html"]
        assert "ACME SL" in call_kwargs["body_html"]

    async def test_envia_reporte_con_failed_bd(self, polling_job: PollingJob):
        """Con failed acumulados en BD, envía reporte incluyéndolos."""
        failed = _make_failed_record_with_steps()
        polling_job._repo.list_failed.return_value = [failed]

        await polling_job.run()

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert "pendiente(s) de resolver" in call_kwargs["subject"]
        assert "Holded API 500" in call_kwargs["body_html"]
        assert "Total con errores" in call_kwargs["body_html"]
        # Verifica que muestra steps con nombres legibles
        assert "Carpeta Drive" in call_kwargs["body_html"]
        assert "Contacto Holded" in call_kwargs["body_html"]

    async def test_reporte_incluye_errores_de_proceso(self, polling_job: PollingJob):
        """Cuando process_deal lanza excepción, aparece en el reporte."""
        deal = _make_enriched_deal(100)
        polling_job._detector.detect_new_deals.return_value = [deal]
        polling_job._manager.process_deal.side_effect = RuntimeError("Connection timeout")

        await polling_job.run()

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert "1 con error" in call_kwargs["subject"]
        assert "Connection timeout" in call_kwargs["body_html"]

    async def test_reporte_incluye_waiting_technician(self, polling_job: PollingJob):
        """Deals en WAITING_TECHNICIAN aparecen en el reporte."""
        deal = _make_enriched_deal(100)
        polling_job._detector.detect_new_deals.return_value = [deal]
        polling_job._manager.process_deal.return_value = _make_record(
            status=OnboardingStatus.WAITING_TECHNICIAN
        )

        await polling_job.run()

        polling_job._gmail.send_email.assert_awaited_once()
        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert "esperando técnico" in call_kwargs["subject"]
        assert "Esperando técnico" in call_kwargs["body_html"]

    async def test_no_envia_email_sin_actividad(self, polling_job: PollingJob):
        """Sin deals nuevos, sin pendientes, sin failed → no envía email."""
        await polling_job.run()

        polling_job._gmail.send_email.assert_not_awaited()

    async def test_email_error_no_crashea(self, polling_job: PollingJob):
        """Si el email de resumen falla, el ciclo no crashea."""
        polling_job._repo.list_failed.return_value = [
            _make_failed_record_with_steps(),
        ]
        polling_job._gmail.send_email.side_effect = RuntimeError("SMTP error")

        await polling_job.run()  # No debe lanzar excepción

    async def test_reporte_mixto_completados_y_errores(self, polling_job: PollingJob):
        """Reporte con completados y errores muestra ambos."""
        deal1 = _make_enriched_deal(100)
        deal2 = _make_enriched_deal(200)
        polling_job._detector.detect_new_deals.return_value = [deal1, deal2]
        polling_job._manager.process_deal.side_effect = [
            _make_record(deal_id=100, status=OnboardingStatus.COMPLETED),
            RuntimeError("API error"),
        ]

        await polling_job.run()

        call_kwargs = polling_job._gmail.send_email.call_args.kwargs
        assert "1 completado(s)" in call_kwargs["subject"]
        assert "1 con error" in call_kwargs["subject"]
        assert "Completados" in call_kwargs["body_html"]
        assert "Errores en este ciclo" in call_kwargs["body_html"]


class TestCleanErrorMessage:
    def test_parsea_json_hubspot(self):
        """Extrae mensaje y scopes de un error JSON de HubSpot."""
        from src.scheduler.polling_job import _clean_error_message

        raw = (
            'HubSpot 403: {"status":"error","message":"This app hasn\'t been granted all required scopes",'
            '"correlationId":"f1abc06c-a32c-4e17-bfc6-1739c77b6eac",'
            '"errors":[{"message":"One or more of the following scopes are required.",'
            '"context":{"requiredGranularScopes":["crm.objects.companies.write"]}}],'
            '"category":"MISSING_SCOPES"}'
        )
        result = _clean_error_message(raw)
        assert "MISSING_SCOPES" in result
        assert "crm.objects.companies.write" in result
        # No debe contener el correlationId
        assert "correlationId" not in result

    def test_limpia_excepcion_no_controlada(self):
        from src.scheduler.polling_job import _clean_error_message

        raw = "Excepción no controlada: Connection refused"
        result = _clean_error_message(raw)
        assert result == "Connection refused"

    def test_trunca_mensajes_largos(self):
        from src.scheduler.polling_job import _clean_error_message

        raw = "x" * 300
        result = _clean_error_message(raw)
        assert len(result) <= 203  # 200 + "..."

    def test_texto_plano_sin_cambios(self):
        from src.scheduler.polling_job import _clean_error_message

        raw = "Timeout al conectar con Holded"
        assert _clean_error_message(raw) == raw


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
