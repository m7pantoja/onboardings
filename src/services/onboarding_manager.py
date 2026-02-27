"""Orquestador principal del proceso de onboarding."""

from __future__ import annotations

import structlog

from src.clients.slack import SlackClient
from src.models.deal import EnrichedDeal
from src.models.enums import OnboardingStatus
from src.models.onboarding import OnboardingRecord, TechnicianInfo
from src.models.sheets import DEPARTMENT_TECHNICIAN_PROPERTIES, Department, TeamMember
from src.persistence.repository import OnboardingRepository
from src.pipeline.engine import PipelineEngine
from src.pipeline.registry import build_pipeline
from src.services.service_mapper import (
    DepartmentNotAssignedError,
    ServiceMapper,
    ServiceNotFoundError,
)
from src.steps.base import StepContext

logger = structlog.get_logger()


class OnboardingManager:
    """Orquesta el proceso completo de onboarding para un deal.

    Para cada EnrichedDeal:
    1. Verifica si ya tiene un record en BD (idempotencia).
    2. Resuelve departamento via ServiceMapper.
    3. Resuelve técnico:
       - Si el departamento tiene propiedades de técnico (SU/FI/AS/LA):
         busca en deal.technicians el que corresponde a ese departamento.
         Si no hay técnico → WAITING_TECHNICIAN + notifica responsable.
       - Si el departamento no tiene propiedades (LE/DA/DI):
         técnico = responsable del departamento (siempre existe).
    4. Ejecuta el pipeline de steps via PipelineEngine.
    """

    def __init__(
        self,
        repository: OnboardingRepository,
        service_mapper: ServiceMapper,
        engine: PipelineEngine,
        slack_client: SlackClient,
        pipeline_clients: dict,
        hubspot_portal_id: int | None = None,
    ) -> None:
        self._repo = repository
        self._mapper = service_mapper
        self._engine = engine
        self._slack = slack_client
        self._pipeline_clients = pipeline_clients
        self._hubspot_portal_id = hubspot_portal_id

    async def process_deal(self, deal: EnrichedDeal) -> OnboardingRecord:
        """Procesa un deal detectado como WON.

        Devuelve el OnboardingRecord con el estado final (puede ser COMPLETED,
        FAILED o WAITING_TECHNICIAN).
        """
        log = logger.bind(deal_id=deal.deal_id, company=deal.company_name)

        # 1. Comprobar si ya existe (no debería llegar aquí si DealDetector filtra bien,
        #    pero lo verificamos como salvaguarda)
        existing = await self._repo.get_by_deal_id(deal.deal_id)
        if existing and existing.status == OnboardingStatus.COMPLETED:
            log.info("onboarding_already_completed")
            return existing

        # 2. Resolver departamento
        try:
            department = await self._mapper.get_department(deal.service_name)
        except ServiceNotFoundError:
            log.warning(
                "service_not_found_skipping",
                service=deal.service_name,
            )
            return await self._save_failed(
                deal,
                error=f"Servicio no encontrado en la Sheet: {deal.service_name!r}",
                existing=existing,
            )
        except DepartmentNotAssignedError:
            log.warning(
                "service_no_department_skipping",
                service=deal.service_name,
            )
            return await self._save_failed(
                deal,
                error=f"Servicio sin departamento asignado: {deal.service_name!r}",
                existing=existing,
            )

        # 3. Resolver técnico
        technician = await self._resolve_technician(deal, department)

        if technician is None:
            return await self._handle_waiting_technician(deal, department, existing)

        # 4. Preparar record y contexto
        record = existing or await self._create_record(deal, department, technician)

        ctx = StepContext.from_enriched_deal(
            deal=deal,
            department=department,
            technician=technician,
            hubspot_portal_id=self._hubspot_portal_id,
        )

        # 5. Construir y ejecutar pipeline
        steps = build_pipeline(**self._pipeline_clients)
        log.info("running_pipeline", department=department.value, technician=technician.nombre_corto)

        return await self._engine.run(record, ctx, steps)

    async def _resolve_technician(
        self, deal: EnrichedDeal, department: Department
    ) -> TeamMember | None:
        """Resuelve el técnico para el deal según el departamento.

        - Departamentos con propiedades (SU/FI/AS/LA): busca en deal.technicians
          los que coinciden con las propiedades del departamento, luego cruza con
          el equipo de la Sheet para obtener datos completos.
        - Departamentos sin propiedades (LE/DA/DI): devuelve el responsable del depto.
        """
        if department not in DEPARTMENT_TECHNICIAN_PROPERTIES:
            # LE, DA, DI: técnico = responsable del departamento
            responsable = await self._mapper.get_responsable(department)
            if responsable:
                logger.info(
                    "technician_resolved_responsable",
                    department=department.value,
                    technician=responsable.nombre_corto,
                )
            return responsable

        # Departamentos con propiedades: buscar técnico en el deal
        dept_properties = DEPARTMENT_TECHNICIAN_PROPERTIES[department]
        dept_technicians = [
            t for t in deal.technicians if t.property_name in dept_properties
        ]

        if not dept_technicians:
            logger.info(
                "no_technician_in_deal",
                department=department.value,
                dept_properties=dept_properties,
            )
            return None

        # Tomar el primer técnico válido y buscar sus datos en la Sheet
        tec_info: TechnicianInfo = dept_technicians[0]
        team_members = await self._mapper.get_team_members(department)

        technician = next(
            (m for m in team_members if m.hubspot_tec_id == tec_info.hubspot_tec_id),
            None,
        )

        if technician is None:
            logger.warning(
                "technician_not_in_sheet",
                hubspot_tec_id=tec_info.hubspot_tec_id,
                department=department.value,
            )
            return None

        logger.info(
            "technician_resolved",
            department=department.value,
            technician=technician.nombre_corto,
        )
        return technician

    async def _handle_waiting_technician(
        self,
        deal: EnrichedDeal,
        department: Department,
        existing: OnboardingRecord | None,
    ) -> OnboardingRecord:
        """Guarda el onboarding como WAITING_TECHNICIAN y notifica al responsable."""
        log = logger.bind(deal_id=deal.deal_id, department=department.value)

        if existing is None:
            record = OnboardingRecord(
                deal_id=deal.deal_id,
                deal_name=deal.deal_name,
                company_name=deal.company_name,
                service_name=deal.service_name,
                department=department.value,
                hubspot_owner_id=deal.hubspot_owner_id,
                technicians=deal.technicians,
                status=OnboardingStatus.WAITING_TECHNICIAN,
            )
            record.id = await self._repo.create(record)
        else:
            await self._repo.update_status(existing.id, OnboardingStatus.WAITING_TECHNICIAN)
            existing.status = OnboardingStatus.WAITING_TECHNICIAN
            record = existing

        log.warning("onboarding_waiting_technician")

        # Notificar al responsable del departamento por Slack
        responsable = await self._mapper.get_responsable(department)
        if responsable and responsable.slack_id:
            from src.models.sheets import DEPARTMENT_LABELS

            dept_label = DEPARTMENT_LABELS.get(department, department.value)
            message = (
                f"⚠️ Nuevo negocio sin técnico asignado:\n"
                f"*{deal.deal_name}*\n"
                f"Empresa: *{deal.company_name}*\n"
                f"Servicio: *{deal.service_name}*\n"
                f"Departamento: *{dept_label}*\n\n"
                f"Por favor, asigna un técnico en HubSpot."
            )
            try:
                await self._slack.send_dm(responsable.slack_id, message)
                log.info(
                    "responsable_notified_no_technician",
                    responsable=responsable.nombre_corto,
                )
            except Exception as exc:
                log.error("slack_notify_responsable_failed", error=str(exc))
        else:
            log.warning("no_responsable_slack_id", department=department.value)

        return record

    async def _create_record(
        self,
        deal: EnrichedDeal,
        department: Department,
        technician: TeamMember,
    ) -> OnboardingRecord:
        """Crea y persiste un nuevo OnboardingRecord."""
        # Solo guardamos los técnicos del departamento correspondiente
        dept_properties = DEPARTMENT_TECHNICIAN_PROPERTIES.get(department, ())
        relevant_technicians = [
            t for t in deal.technicians if t.property_name in dept_properties
        ]

        record = OnboardingRecord(
            deal_id=deal.deal_id,
            deal_name=deal.deal_name,
            company_name=deal.company_name,
            service_name=deal.service_name,
            department=department.value,
            hubspot_owner_id=deal.hubspot_owner_id,
            technicians=relevant_technicians,
            status=OnboardingStatus.PENDING,
        )
        record.id = await self._repo.create(record)
        return record

    async def _save_failed(
        self,
        deal: EnrichedDeal,
        error: str,
        existing: OnboardingRecord | None,
    ) -> OnboardingRecord:
        """Guarda o actualiza el onboarding con estado FAILED."""
        if existing is None:
            record = OnboardingRecord(
                deal_id=deal.deal_id,
                deal_name=deal.deal_name,
                company_name=deal.company_name,
                service_name=deal.service_name,
                hubspot_owner_id=deal.hubspot_owner_id,
                status=OnboardingStatus.FAILED,
            )
            record.id = await self._repo.create(record)
        else:
            await self._repo.update_status(existing.id, OnboardingStatus.FAILED)
            existing.status = OnboardingStatus.FAILED
            record = existing

        logger.error(
            "onboarding_failed_before_pipeline",
            deal_id=deal.deal_id,
            error=error,
        )
        return record
