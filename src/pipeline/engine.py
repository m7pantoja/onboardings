"""Motor de ejecución del pipeline de onboarding."""

from __future__ import annotations

from datetime import datetime

import structlog

from src.models.enums import OnboardingStatus, StepStatus
from src.models.onboarding import OnboardingRecord, StepRecord
from src.persistence.repository import OnboardingRepository
from src.steps.base import BaseStep, StepContext

logger = structlog.get_logger()


class PipelineEngine:
    """Ejecuta los steps de un onboarding en orden, persistiendo el estado de cada uno.

    Política de errores:
    - Si un step falla, se registra el error y se continúa con el siguiente.
    - Al finalizar, el onboarding queda COMPLETED si todos los steps tuvieron éxito,
      o FAILED si alguno falló (para reintento en el siguiente polling).
    - Los steps ya completados (check_already_done) se saltan automáticamente.
    """

    def __init__(self, repository: OnboardingRepository) -> None:
        self._repo = repository

    async def run(
        self,
        record: OnboardingRecord,
        ctx: StepContext,
        steps: list[BaseStep],
    ) -> OnboardingRecord:
        """Ejecuta el pipeline completo para un onboarding.

        Args:
            record: OnboardingRecord ya persistido (con id asignado).
            ctx: Contexto compartido con datos del deal y técnico.
            steps: Lista de steps a ejecutar en orden.

        Returns:
            El OnboardingRecord actualizado con el estado final.
        """
        assert record.id is not None, "El record debe tener id antes de ejecutar el pipeline"

        log = logger.bind(onboarding_id=record.id, deal_id=record.deal_id)
        log.info("pipeline_started", steps_count=len(steps))

        # Actualizar estado a IN_PROGRESS
        await self._repo.update_status(record.id, OnboardingStatus.IN_PROGRESS)
        record.status = OnboardingStatus.IN_PROGRESS

        failed_steps: list[str] = []

        for step in steps:
            step_log = log.bind(step=step.name.value)

            # Marcar step como IN_PROGRESS en BD
            step_record = StepRecord(
                onboarding_id=record.id,
                step_name=step.name,
                status=StepStatus.IN_PROGRESS,
                started_at=datetime.now(),
            )
            await self._repo.upsert_step(step_record)
            await self._repo.update_status(record.id, OnboardingStatus.IN_PROGRESS, step.name)
            record.current_step = step.name

            step_log.info("step_started")

            try:
                result = await step.run(ctx)
            except Exception as exc:
                # Error inesperado (no manejado por el step)
                step_log.error("step_exception", error=str(exc))
                step_record = StepRecord(
                    onboarding_id=record.id,
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    error_message=f"Excepción no controlada: {exc}",
                    started_at=step_record.started_at,
                    completed_at=datetime.now(),
                )
                await self._repo.upsert_step(step_record)
                failed_steps.append(step.name.value)
                continue

            if result.data.get("skipped"):
                step_record = StepRecord(
                    onboarding_id=record.id,
                    step_name=step.name,
                    status=StepStatus.SKIPPED,
                    result_data=result.data,
                    started_at=step_record.started_at,
                    completed_at=datetime.now(),
                )
                await self._repo.upsert_step(step_record)
                step_log.info("step_skipped")
                continue

            if result.success:
                step_record = StepRecord(
                    onboarding_id=record.id,
                    step_name=step.name,
                    status=StepStatus.COMPLETED,
                    result_data=result.data,
                    started_at=step_record.started_at,
                    completed_at=datetime.now(),
                )
                await self._repo.upsert_step(step_record)
                step_log.info("step_completed", data=result.data)
            else:
                step_record = StepRecord(
                    onboarding_id=record.id,
                    step_name=step.name,
                    status=StepStatus.FAILED,
                    error_message=result.error,
                    started_at=step_record.started_at,
                    completed_at=datetime.now(),
                )
                await self._repo.upsert_step(step_record)
                step_log.warning("step_failed", error=result.error)
                failed_steps.append(step.name.value)

        # Estado final del onboarding
        if failed_steps:
            final_status = OnboardingStatus.FAILED
            log.warning(
                "pipeline_completed_with_failures",
                failed_steps=failed_steps,
            )
        else:
            final_status = OnboardingStatus.COMPLETED
            log.info("pipeline_completed_successfully")

        await self._repo.update_status(record.id, final_status, current_step=None)
        record.status = final_status
        record.current_step = None

        return record
