import logging
from datetime import datetime, timezone
from uuid import UUID
import asyncio
import json

from ..db.redis_client import RedisClient
from ..db.db_client import AsyncPostgresClient
from ..models.db_models import Attendance, AttendanceRecord, User
from ..models.redis_models import AttendanceRedis, AttendanceRecordRedis

# Configure logging for the cron tasks
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def unified_persistence_task(redis_client: RedisClient, db_client: AsyncPostgresClient):
    """
    This is the refactored, unified task that guarantees data integrity.
    It runs periodically to process attendance sessions whose end_time has passed.
    """
    logger.info("Running unified_persistence_task...")
    now = datetime.now(timezone.utc)

    async for session_key in redis_client._redis.scan_iter("attendance_session:*"):
        attendance_session: AttendanceRedis = None
        try:
            session_json = await redis_client._redis.get(session_key)
            if not session_json:
                continue
            
            attendance_session = AttendanceRedis.model_validate_json(session_json)
            attendance_id = attendance_session.attendance_id

            if attendance_session.end_time >= now:
                continue

            logger.info(f"Processing expired attendance session: {attendance_id}")

            # --- DB Persistence (Strict Order) ---
            teacher_user = User(
                user_school_number=attendance_session.teacher_school_number,
                user_full_name=attendance_session.teacher_full_name,
                role="Teacher"
            )
            await db_client.add_users([teacher_user])

            associated_redis_records = await redis_client.get_attendance_records(attendance_id)

            students_to_upsert = []
            records_to_db = []
            if associated_redis_records:
                for rec in associated_redis_records:
                    students_to_upsert.append(
                        User(user_school_number=rec.student_number, user_full_name=rec.student_full_name, role="Student")
                    )
                    records_to_db.append(AttendanceRecord(**rec.model_dump(include={'attendance_id', 'student_number', 'is_attended', 'attendance_time', 'fail_reason'})))
                await db_client.add_users(students_to_upsert)

            attendance_to_db = Attendance(**attendance_session.model_dump())
            await db_client.add_attendances([attendance_to_db])

            if records_to_db:
                await db_client.add_attendance_records(records_to_db)
                logger.info(f"Saved {len(records_to_db)} student records for session {attendance_id}.")

            # --- Redis Cleanup ---
            logger.info(f"Cleaning up Redis for session {attendance_id}...")
            await redis_client.delete_attendance_session(attendance_session)

            record_keys_to_delete = [f"attendance_records:{attendance_id}:{rec.student_number}" for rec in associated_redis_records]
            if record_keys_to_delete:
                await redis_client._redis.delete(*record_keys_to_delete)
            
            logger.info(f"Cleanup complete for session {attendance_id}.")

        except Exception as e:
            session_id_for_log = attendance_session.attendance_id if attendance_session else f"from key {session_key}"
            logger.error(f"Failed to process session {session_id_for_log}: {e}", exc_info=True)


