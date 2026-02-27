import json
from datetime import datetime
from pathlib import Path

import aiosqlite
import structlog

from src.models.enums import OnboardingStatus, StepName, StepStatus
from src.models.onboarding import OnboardingRecord, StepRecord, TechnicianInfo

logger = structlog.get_logger()

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class OnboardingRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        """Crea las tablas si no existen."""
        async with aiosqlite.connect(self._db_path) as db:
            schema = SCHEMA_PATH.read_text()
            await db.executescript(schema)
            await db.commit()
        logger.info("database_initialized", path=str(self._db_path))

    async def _load_technicians(
        self, db: aiosqlite.Connection, onboarding_id: int
    ) -> list[TechnicianInfo]:
        cursor = await db.execute(
            "SELECT hubspot_tec_id, property_name FROM onboarding_technicians WHERE onboarding_id = ?",
            (onboarding_id,),
        )
        rows = await cursor.fetchall()
        return [
            TechnicianInfo(hubspot_tec_id=r["hubspot_tec_id"], property_name=r["property_name"])
            for r in rows
        ]

    async def _load_steps(
        self, db: aiosqlite.Connection, onboarding_id: int
    ) -> list[StepRecord]:
        cursor = await db.execute(
            "SELECT * FROM onboarding_steps WHERE onboarding_id = ?",
            (onboarding_id,),
        )
        rows = await cursor.fetchall()
        return [
            StepRecord(
                onboarding_id=s["onboarding_id"],
                step_name=StepName(s["step_name"]),
                status=StepStatus(s["status"]),
                result_data=json.loads(s["result_data"]) if s["result_data"] else None,
                error_message=s["error_message"],
                started_at=datetime.fromisoformat(s["started_at"]) if s["started_at"] else None,
                completed_at=datetime.fromisoformat(s["completed_at"]) if s["completed_at"] else None,
            )
            for s in rows
        ]

    def _row_to_record(self, row: aiosqlite.Row) -> OnboardingRecord:
        return OnboardingRecord(
            id=row["id"],
            deal_id=row["deal_id"],
            deal_name=row["deal_name"],
            company_name=row["company_name"],
            service_name=row["service_name"],
            department=row["department"],
            hubspot_owner_id=row["hubspot_owner_id"],
            status=OnboardingStatus(row["status"]),
            current_step=StepName(row["current_step"]) if row["current_step"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def get_by_deal_id(self, deal_id: int) -> OnboardingRecord | None:
        """Busca un onboarding por deal_id. None si no existe."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM onboardings WHERE deal_id = ?", (deal_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            record = self._row_to_record(row)
            record.technicians = await self._load_technicians(db, record.id)
            record.steps = await self._load_steps(db, record.id)
            return record

    async def create(self, record: OnboardingRecord) -> int:
        """Inserta un nuevo onboarding con sus técnicos. Devuelve el id generado."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO onboardings
                   (deal_id, deal_name, company_name, service_name, department,
                    hubspot_owner_id, status, current_step)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.deal_id,
                    record.deal_name,
                    record.company_name,
                    record.service_name,
                    record.department,
                    record.hubspot_owner_id,
                    record.status.value,
                    record.current_step.value if record.current_step else None,
                ),
            )
            onboarding_id = cursor.lastrowid

            for tech in record.technicians:
                await db.execute(
                    """INSERT INTO onboarding_technicians
                       (onboarding_id, hubspot_tec_id, property_name)
                       VALUES (?, ?, ?)""",
                    (onboarding_id, tech.hubspot_tec_id, tech.property_name),
                )

            await db.commit()
        logger.info("onboarding_created", deal_id=record.deal_id, id=onboarding_id)
        return onboarding_id

    async def update_status(
        self, onboarding_id: int, status: OnboardingStatus, current_step: StepName | None = None
    ) -> None:
        """Actualiza el estado del onboarding."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE onboardings
                   SET status = ?, current_step = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    status.value,
                    current_step.value if current_step else None,
                    onboarding_id,
                ),
            )
            await db.commit()

    async def upsert_step(self, step: StepRecord) -> None:
        """Inserta o actualiza el estado de un step."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO onboarding_steps
                   (onboarding_id, step_name, status, result_data, error_message,
                    started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(onboarding_id, step_name) DO UPDATE SET
                    status = excluded.status,
                    result_data = excluded.result_data,
                    error_message = excluded.error_message,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at""",
                (
                    step.onboarding_id,
                    step.step_name.value,
                    step.status.value,
                    json.dumps(step.result_data) if step.result_data else None,
                    step.error_message,
                    step.started_at.isoformat() if step.started_at else None,
                    step.completed_at.isoformat() if step.completed_at else None,
                ),
            )
            await db.commit()

    async def list_failed(self) -> list[OnboardingRecord]:
        """Devuelve onboardings en estado FAILED (para resumen al admin)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM onboardings WHERE status = ? ORDER BY created_at",
                (OnboardingStatus.FAILED.value,),
            )
            rows = await cursor.fetchall()
            records = []
            for row in rows:
                record = self._row_to_record(row)
                record.technicians = await self._load_technicians(db, record.id)
                records.append(record)
            return records

    async def list_pending(self) -> list[OnboardingRecord]:
        """Devuelve onboardings pendientes, esperando técnico o en progreso (para retomar)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM onboardings
                   WHERE status IN (?, ?, ?)
                   ORDER BY created_at""",
                (
                    OnboardingStatus.PENDING.value,
                    OnboardingStatus.WAITING_TECHNICIAN.value,
                    OnboardingStatus.IN_PROGRESS.value,
                ),
            )
            rows = await cursor.fetchall()
            records = []
            for row in rows:
                record = self._row_to_record(row)
                record.technicians = await self._load_technicians(db, record.id)
                records.append(record)
            return records
