"""Tests para el PipelineEngine y OnboardingManager."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.deal import CompanyInfo, ContactPersonInfo, EnrichedDeal
from src.models.enums import OnboardingStatus, StepName, StepStatus
from src.models.onboarding import OnboardingRecord, TechnicianInfo
from src.models.sheets import Department, TeamMember
from src.pipeline.engine import PipelineEngine
from src.services.onboarding_manager import OnboardingManager
from src.services.service_mapper import DepartmentNotAssignedError, ServiceNotFoundError
from src.steps.base import BaseStep, StepContext, StepResult


# ── Helpers ──────────────────────────────────────────────────────


def _make_record(**overrides) -> OnboardingRecord:
    defaults = dict(
        id=1,
        deal_id=12345,
        deal_name="Acme Corp - Asesoramiento fiscal",
        company_name="Acme Corp",
        service_name="Asesoramiento fiscal",
        department=Department.AS.value,
        hubspot_owner_id=99,
        status=OnboardingStatus.PENDING,
    )
    defaults.update(overrides)
    return OnboardingRecord(**defaults)


def _make_ctx(**overrides) -> StepContext:
    defaults = dict(
        deal_id=12345,
        deal_name="Acme Corp - Asesoramiento fiscal",
        company_name="Acme Corp",
        service_name="Asesoramiento fiscal",
        department=Department.AS,
        technician=TeamMember(
            hubspot_tec_id="tec_789",
            slack_id="U06MRGSBQS3",
            email="esther@leanfinance.es",
            nombre_completo="Esther Punzano López",
            nombre_corto="Esther",
            department=Department.AS,
            is_responsable=True,
        ),
    )
    defaults.update(overrides)
    return StepContext(**defaults)


def _make_step(name: StepName, *, success: bool = True, skip: bool = False) -> BaseStep:
    """Crea un step mock con resultado predeterminado."""
    step = AsyncMock(spec=BaseStep)
    step.name = name
    if skip:
        step.run = AsyncMock(return_value=StepResult(success=True, data={"skipped": True}))
    elif success:
        step.run = AsyncMock(return_value=StepResult(success=True, data={"key": "value"}))
    else:
        step.run = AsyncMock(return_value=StepResult(success=False, error="Error simulado"))
    return step


def _make_enriched_deal(**overrides) -> EnrichedDeal:
    defaults = dict(
        deal_id=12345,
        deal_name="Acme Corp - Asesoramiento fiscal",
        company_name="Acme Corp",
        service_name="Asesoramiento fiscal",
        close_date=datetime.now(),
        hubspot_owner_id=99,
        company=CompanyInfo(company_id="comp_1", name="Acme Corp"),
        contact_person=ContactPersonInfo(contact_id="cont_1", firstname="Juan"),
        technicians=[
            TechnicianInfo(hubspot_tec_id="tec_789", property_name="asesor_fiscal_asignado")
        ],
    )
    defaults.update(overrides)
    return EnrichedDeal(**defaults)


def _make_team_member(**overrides) -> TeamMember:
    defaults = dict(
        hubspot_tec_id="tec_789",
        slack_id="U06MRGSBQS3",
        email="esther@leanfinance.es",
        nombre_completo="Esther Punzano López",
        nombre_corto="Esther",
        department=Department.AS,
        is_responsable=True,
    )
    defaults.update(overrides)
    return TeamMember(**defaults)


# ── Tests PipelineEngine ─────────────────────────────────────────


class TestPipelineEngine:
    async def test_todos_los_steps_completan(self) -> None:
        """Si todos los steps tienen éxito, el onboarding queda COMPLETED."""
        repo = AsyncMock()
        engine = PipelineEngine(repo)

        record = _make_record()
        ctx = _make_ctx()
        steps = [
            _make_step(StepName.CREATE_DRIVE_FOLDER),
            _make_step(StepName.CREATE_HOLDED_CONTACT),
            _make_step(StepName.NOTIFY_SLACK),
            _make_step(StepName.SEND_EMAIL),
        ]

        result = await engine.run(record, ctx, steps)

        assert result.status == OnboardingStatus.COMPLETED
        # upsert_step: 4 veces para marcar IN_PROGRESS + 4 para marcar COMPLETED = 8
        assert repo.upsert_step.call_count == 8
        # update_status: 1 inicial IN_PROGRESS + 4 current_step + 1 final COMPLETED = 6
        assert repo.update_status.call_count == 6

    async def test_step_fallido_continua_pipeline(self) -> None:
        """Si un step falla, los siguientes se ejecutan igualmente."""
        repo = AsyncMock()
        engine = PipelineEngine(repo)

        record = _make_record()
        ctx = _make_ctx()
        steps = [
            _make_step(StepName.CREATE_DRIVE_FOLDER, success=False),
            _make_step(StepName.CREATE_HOLDED_CONTACT),
            _make_step(StepName.NOTIFY_SLACK),
        ]

        result = await engine.run(record, ctx, steps)

        assert result.status == OnboardingStatus.FAILED
        # El step 2 y 3 sí se ejecutaron
        steps[1].run.assert_called_once()
        steps[2].run.assert_called_once()

    async def test_step_skipped_no_cuenta_como_fallo(self) -> None:
        """Un step que devuelve skipped=True se persiste como SKIPPED, no como fallo."""
        repo = AsyncMock()
        engine = PipelineEngine(repo)

        record = _make_record()
        ctx = _make_ctx()
        steps = [
            _make_step(StepName.CREATE_DRIVE_FOLDER, skip=True),
            _make_step(StepName.NOTIFY_SLACK),
        ]

        result = await engine.run(record, ctx, steps)

        assert result.status == OnboardingStatus.COMPLETED

        # Verificar que el step skipped se persistió con status SKIPPED
        step_calls = repo.upsert_step.call_args_list
        skipped_call = next(
            (c for c in step_calls if c.args[0].step_name == StepName.CREATE_DRIVE_FOLDER
             and c.args[0].status == StepStatus.SKIPPED),
            None,
        )
        assert skipped_call is not None

    async def test_step_con_excepcion_continua_pipeline(self) -> None:
        """Si un step lanza una excepción, se captura y el pipeline continúa."""
        repo = AsyncMock()
        engine = PipelineEngine(repo)

        step_falla = AsyncMock(spec=BaseStep)
        step_falla.name = StepName.CREATE_DRIVE_FOLDER
        step_falla.run = AsyncMock(side_effect=RuntimeError("API down"))

        step_ok = _make_step(StepName.NOTIFY_SLACK)

        record = _make_record()
        ctx = _make_ctx()

        result = await engine.run(record, ctx, [step_falla, step_ok])

        assert result.status == OnboardingStatus.FAILED
        step_ok.run.assert_called_once()

    async def test_pipeline_vacio_completa(self) -> None:
        """Un pipeline sin steps completa inmediatamente como COMPLETED."""
        repo = AsyncMock()
        engine = PipelineEngine(repo)

        record = _make_record()
        ctx = _make_ctx()

        result = await engine.run(record, ctx, steps=[])

        assert result.status == OnboardingStatus.COMPLETED


# ── Tests OnboardingManager ──────────────────────────────────────


def _make_manager(
    *,
    repo=None,
    mapper=None,
    engine=None,
    slack=None,
) -> OnboardingManager:
    """Crea un OnboardingManager con mocks por defecto."""
    return OnboardingManager(
        repository=repo or AsyncMock(),
        service_mapper=mapper or AsyncMock(),
        engine=engine or AsyncMock(),
        slack_client=slack or AsyncMock(),
        pipeline_clients={
            "drive_client": AsyncMock(),
            "holded_client": AsyncMock(),
            "slack_client": AsyncMock(),
            "gmail_client": AsyncMock(),
            "hubspot_client": AsyncMock(),
        },
        hubspot_portal_id=6575051,
    )


class TestOnboardingManagerResolveTechnician:
    async def test_departamento_sin_propiedades_usa_responsable(self) -> None:
        """Departamentos LE/DA/DI usan el responsable como técnico."""
        responsable = _make_team_member(department=Department.DA, is_responsable=True)
        mapper = AsyncMock()
        mapper.get_responsable = AsyncMock(return_value=responsable)

        manager = _make_manager(mapper=mapper)
        deal = _make_enriched_deal(technicians=[])  # sin técnicos en el deal

        technician = await manager._resolve_technician(deal, Department.DA)

        assert technician == responsable
        mapper.get_responsable.assert_called_once_with(Department.DA)

    async def test_departamento_con_propiedad_resuelve_por_id(self) -> None:
        """Departamentos con propiedades buscan el técnico por hubspot_tec_id en la Sheet."""
        tec = _make_team_member(hubspot_tec_id="tec_789", department=Department.AS)
        mapper = AsyncMock()
        mapper.get_team_members = AsyncMock(return_value=[tec])

        deal = _make_enriched_deal(
            technicians=[TechnicianInfo(hubspot_tec_id="tec_789", property_name="asesor_fiscal_asignado")]
        )

        manager = _make_manager(mapper=mapper)
        technician = await manager._resolve_technician(deal, Department.AS)

        assert technician == tec

    async def test_sin_tecnico_en_deal_devuelve_none(self) -> None:
        """Si no hay técnicos para el departamento en el deal, devuelve None."""
        mapper = AsyncMock()
        deal = _make_enriched_deal(technicians=[])  # deal sin técnicos

        manager = _make_manager(mapper=mapper)
        technician = await manager._resolve_technician(deal, Department.SU)

        assert technician is None

    async def test_tecnico_no_encontrado_en_sheet_devuelve_none(self) -> None:
        """Si el hubspot_tec_id del deal no está en la Sheet, devuelve None."""
        mapper = AsyncMock()
        mapper.get_team_members = AsyncMock(return_value=[])  # Sheet vacía

        deal = _make_enriched_deal(
            technicians=[TechnicianInfo(hubspot_tec_id="tec_desconocido", property_name="asesor_fiscal_asignado")]
        )

        manager = _make_manager(mapper=mapper)
        technician = await manager._resolve_technician(deal, Department.AS)

        assert technician is None


class TestOnboardingManagerProcessDeal:
    async def test_onboarding_ya_completado_no_reprocesa(self) -> None:
        """Si el deal ya tiene un record COMPLETED, se devuelve directamente."""
        existing = _make_record(status=OnboardingStatus.COMPLETED)
        repo = AsyncMock()
        repo.get_by_deal_id = AsyncMock(return_value=existing)

        manager = _make_manager(repo=repo)
        result = await manager.process_deal(_make_enriched_deal())

        assert result.status == OnboardingStatus.COMPLETED
        # No se llama al mapper ni al engine
        manager._mapper.get_department.assert_not_called()
        manager._engine.run.assert_not_called()

    async def test_servicio_no_encontrado_guarda_failed(self) -> None:
        """Si el servicio no está en la Sheet, el onboarding queda FAILED."""
        repo = AsyncMock()
        repo.get_by_deal_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=1)

        mapper = AsyncMock()
        mapper.get_department = AsyncMock(
            side_effect=ServiceNotFoundError("Asesoramiento fiscal")
        )

        manager = _make_manager(repo=repo, mapper=mapper)
        result = await manager.process_deal(_make_enriched_deal())

        assert result.status == OnboardingStatus.FAILED

    async def test_sin_tecnico_guarda_waiting_y_notifica(self) -> None:
        """Si no hay técnico, el status queda WAITING_TECHNICIAN y se avisa al responsable."""
        repo = AsyncMock()
        repo.get_by_deal_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=1)

        responsable = _make_team_member(is_responsable=True, slack_id="U_RESP")
        mapper = AsyncMock()
        mapper.get_department = AsyncMock(return_value=Department.AS)
        mapper.get_team_members = AsyncMock(return_value=[])  # sin técnicos en el deal
        mapper.get_responsable = AsyncMock(return_value=responsable)

        slack = AsyncMock()
        manager = _make_manager(repo=repo, mapper=mapper, slack=slack)

        deal = _make_enriched_deal(technicians=[])  # sin técnico en HubSpot

        result = await manager.process_deal(deal)

        assert result.status == OnboardingStatus.WAITING_TECHNICIAN
        slack.send_dm.assert_called_once()
        args = slack.send_dm.call_args
        assert args.args[0] == "U_RESP"

    async def test_flujo_completo_con_tecnico(self) -> None:
        """Con técnico resuelto, se ejecuta el pipeline y se devuelve su resultado."""
        repo = AsyncMock()
        repo.get_by_deal_id = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=42)

        tec = _make_team_member(hubspot_tec_id="tec_789", department=Department.AS)
        mapper = AsyncMock()
        mapper.get_department = AsyncMock(return_value=Department.AS)
        mapper.get_team_members = AsyncMock(return_value=[tec])

        completed_record = _make_record(id=42, status=OnboardingStatus.COMPLETED)
        engine = AsyncMock()
        engine.run = AsyncMock(return_value=completed_record)

        manager = _make_manager(repo=repo, mapper=mapper, engine=engine)

        deal = _make_enriched_deal(
            technicians=[TechnicianInfo(hubspot_tec_id="tec_789", property_name="asesor_fiscal_asignado")]
        )

        with patch("src.services.onboarding_manager.build_pipeline", return_value=[]):
            result = await manager.process_deal(deal)

        assert result.status == OnboardingStatus.COMPLETED
        engine.run.assert_called_once()
