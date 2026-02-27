"""Entry point del sistema de onboardings automatizados.

Uso:
    uv run python main.py          # Scheduler: polling a las 10:00 y 13:50
    uv run python main.py --now    # Ejecución inmediata (un solo ciclo)
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import traceback

import structlog

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.logging import setup_logging
from config.settings import settings
from src.clients.gmail import GmailClient
from src.clients.google_drive import GoogleDriveClient
from src.clients.google_sheets import GoogleSheetsClient
from src.clients.holded import HoldedClient
from src.clients.hubspot import HubSpotClient
from src.clients.slack import SlackClient
from src.persistence.repository import OnboardingRepository
from src.pipeline.engine import PipelineEngine
from src.scheduler.polling_job import PollingJob
from src.services.deal_detector import DealDetector
from src.services.onboarding_manager import OnboardingManager
from src.services.service_mapper import ServiceMapper

logger = structlog.get_logger()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Onboardings automation - LeanFinance")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Ejecutar un ciclo de polling inmediato y salir",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    setup_logging(settings.log_level)

    log = logger.bind(mode="now" if args.now else "scheduler")
    log.info("starting")

    # Inicializar base de datos
    repo = OnboardingRepository(settings.database_path)
    await repo.initialize()

    # Abrir todos los clientes (se mantienen abiertos toda la vida del proceso)
    async with (
        HubSpotClient(token=settings.hubspot_token) as hubspot_client,
        GoogleDriveClient() as drive_client,
        GoogleSheetsClient(spreadsheet_id=settings.google_spreadsheet_id) as sheets_client,
        HoldedClient(api_key=settings.holded_api_key) as holded_client,
        SlackClient(bot_token=settings.slack_bot_token) as slack_client,
        GmailClient() as gmail_client,
    ):
        # Construir servicios
        service_mapper = ServiceMapper(sheets_client)
        engine = PipelineEngine(repo)

        manager = OnboardingManager(
            repository=repo,
            service_mapper=service_mapper,
            engine=engine,
            slack_client=slack_client,
            pipeline_clients={
                "drive_client": drive_client,
                "holded_client": holded_client,
                "slack_client": slack_client,
                "gmail_client": gmail_client,
                "hubspot_client": hubspot_client,
            },
            hubspot_portal_id=settings.hubspot_portal_id,
        )

        detector = DealDetector(
            client=hubspot_client,
            repository=repo,
        )

        polling_job = PollingJob(
            detector=detector,
            manager=manager,
            repository=repo,
            gmail_client=gmail_client,
            admin_email=str(settings.admin_email),
        )

        if args.now:
            log.info("running_single_cycle")
            await polling_job.run()
            log.info("single_cycle_completed")
            return

        # Modo scheduler
        await _run_scheduler(polling_job, log)


async def _run_scheduler(polling_job: PollingJob, log: structlog.stdlib.BoundLogger) -> None:
    """Configura APScheduler y ejecuta hasta recibir señal de parada."""
    scheduler = AsyncIOScheduler(timezone="Europe/Madrid")

    scheduler.add_job(
        polling_job.run,
        trigger="cron",
        hour=10,
        minute=0,
        id="polling_morning",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        polling_job.run,
        trigger="cron",
        hour=13,
        minute=50,
        id="polling_afternoon",
        replace_existing=True,
        misfire_grace_time=300,
    )

    def on_job_error(event: JobExecutionEvent) -> None:
        if event.exception:
            tb = "".join(traceback.format_exception(
                type(event.exception), event.exception, event.exception.__traceback__
            ))
            asyncio.create_task(
                polling_job.notify_critical_error(event.exception, tb)
            )

    scheduler.add_listener(on_job_error, EVENT_JOB_ERROR)
    scheduler.start()

    log.info(
        "scheduler_started",
        jobs=["polling_morning (10:00)", "polling_afternoon (13:50)"],
        timezone="Europe/Madrid",
    )

    # Esperar hasta señal de parada
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        log.info("shutdown_signal_received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    log.info("shutting_down")
    scheduler.shutdown(wait=True)
    log.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
