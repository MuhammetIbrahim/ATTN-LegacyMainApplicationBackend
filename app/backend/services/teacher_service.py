import logging
from typing import List, Optional, Union
from uuid import UUID, uuid4
from datetime import datetime, timezone
import asyncio

# --- Required clients and models ---
from ..db.redis_client import RedisClient
from ..db.db_client import AsyncPostgresClient
from ..models.db_models import User, Attendance, AttendanceRecord
from ..models.redis_models import AttendanceRedis, AttendanceRecordRedis

logger = logging.getLogger(__name__)

# --- Custom Service Layer Exception Classes ---
class ServiceError(Exception):
    """General exception class for the service layer."""
    pass

class AuthorizationError(ServiceError):
    """Exception class for authorization-related errors."""
    pass

# --- Enriched Model for API Responses ---
class EnrichedAttendanceRecord(AttendanceRecord):
    """Attendance record model enriched with student user data."""
    student: User

class TeacherService:
    """
    Service layer that handles all business logic related to teachers.
    """
    def __init__(self, redis_client: RedisClient, db_client: AsyncPostgresClient):
        self.redis_client = redis_client
        self.db_client = db_client

    async def _enrich_records_with_user_data(self, records: List[Union[AttendanceRecord, AttendanceRecordRedis]]) -> List[EnrichedAttendanceRecord]:
        if not records:
            return []
        
        db_records_to_process = [rec for rec in records if isinstance(rec, AttendanceRecord)]
        redis_records_to_process = [rec for rec in records if isinstance(rec, AttendanceRecordRedis)]

        student_numbers_to_fetch = {rec.student_number for rec in db_records_to_process}
        user_map = {}
        if student_numbers_to_fetch:
            try:
                users = await self.db_client.get_users(list(student_numbers_to_fetch))
                user_map = {user.user_school_number: user for user in users}
            except Exception as e:
                logger.error("Database error while enriching records.", exc_info=True)
                raise ServiceError("A database error occurred while fetching user information.") from e

        enriched_records = []
        for record in redis_records_to_process:
            student_user = User(user_school_number=record.student_number, user_full_name=record.student_full_name, role="Student")
            enriched_records.append(EnrichedAttendanceRecord(**record.model_dump(), student=student_user))

        for record in db_records_to_process:
            student_user = user_map.get(record.student_number)
            if student_user:
                enriched_records.append(EnrichedAttendanceRecord(**record.model_dump(), student=student_user))
            else:
                logger.warning(f"User data not found for student ({record.student_number}) in historical attendance record.")
        
        return enriched_records
    
    async def start_attendance(self, teacher: User, lesson_name: str, ip_address: Optional[str], start_time: datetime, end_time: datetime, security_option: int) -> AttendanceRedis:
        existing_session = await self.redis_client.get_attendance_session_of_teacher(teacher.user_school_number)
        if existing_session:
            logger.warning(f"Teacher '{teacher.user_school_number}' tried to start a new session while having an active one.")
            raise ServiceError("You already have an active attendance session. Please end it first.")

        new_attendance_session = AttendanceRedis(
            attendance_id=uuid4(),
            teacher_school_number=teacher.user_school_number,
            teacher_full_name=teacher.user_full_name,
            lesson_name=lesson_name,
            ip_address=ip_address,
            start_time=start_time,
            end_time=end_time,
            security_option=security_option
        )
        
        try:
            await self.redis_client.save_attendance_session(new_attendance_session)
            logger.info(f"Attendance {new_attendance_session.attendance_id} successfully created and indexed in Redis.")
            return new_attendance_session
        except Exception as e:
            logger.error(f"Error adding attendance {new_attendance_session.attendance_id} to Redis.", exc_info=True)
            raise ServiceError("A server error occurred while starting the attendance.") from e

    # --- CORRECTED METHOD ---
    async def finish_attendance(self, teacher: User, attendance_id: UUID) -> None:
        """
        Finishes an attendance session by setting its end_time to now,
        making it eligible for the cron job to process. It DOES NOT delete the data.
        """
        try:
            session_to_finish = await self.redis_client.get_attendance_session(attendance_id)
            if not session_to_finish or session_to_finish.teacher_school_number != teacher.user_school_number:
                raise AuthorizationError("Attendance not found or you are not authorized to end it.")
            
            # Update the end time to the current time.
            session_to_finish.end_time = datetime.now(timezone.utc)
            
            # Save the updated session back to Redis.
            # This makes it "expired" and ready for the cron job.
            await self.redis_client.save_attendance_session(session_to_finish)
            
            logger.info(f"Attendance {attendance_id} marked as finished. Cron job will process for persistence.")
        except AuthorizationError as e:
            logger.warning(f"Unauthorized attempt to finish attendance: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error while finishing attendance {attendance_id}.", exc_info=True)
            raise ServiceError("A server error occurred while finishing the attendance.") from e
            
    async def get_live_attendance_by_teacher(self, teacher: User) -> Optional[AttendanceRedis]:
        try:
            return await self.redis_client.get_attendance_session_of_teacher(teacher.user_school_number)
        except Exception as e:
            logger.error(f"Error getting active session for teacher: {e}", exc_info=True)
            return None

    async def get_and_verify_attendance_owner(self, attendance_id: UUID, teacher: User) -> Union[Attendance, AttendanceRedis]:
        live_session = await self.redis_client.get_attendance_session(attendance_id)
        if live_session:
            if live_session.teacher_school_number == teacher.user_school_number:
                return live_session
            else:
                raise AuthorizationError("You are not authorized to access this live attendance.")
        
        db_attendance = await self.db_client.get_attendance_by_id(attendance_id)
        if not db_attendance or db_attendance.teacher_school_number != teacher.user_school_number:
            raise AuthorizationError("Attendance not found or you are not authorized to access it.")
        return db_attendance

    async def get_live_attendance_records(self, attendance_id: UUID) -> List[EnrichedAttendanceRecord]:
        records = await self.redis_client.get_attendance_records(attendance_id)
        return await self._enrich_records_with_user_data(records)

    async def accept_student_attendance(self, attendance_id: UUID, student_school_number: str) -> Optional[EnrichedAttendanceRecord]:
        try:
            target_record = await self.redis_client.get_attendance_record_by_id(attendance_id, student_school_number)
            if not target_record: return None
            
            target_record.is_attended = True
            target_record.attendance_time = datetime.now(timezone.utc)
            target_record.fail_reason = None
            
            await self.redis_client.update_attendance_record(target_record)
            enriched_list = await self._enrich_records_with_user_data([target_record])
            return enriched_list[0] if enriched_list else None
        except Exception as e:
            logger.error(f"Error while accepting student {student_school_number}.", exc_info=True)
            raise ServiceError("A server error occurred while accepting the student.") from e

    async def fail_student_in_live_attendance(self, attendance_id: UUID, student_school_number: str, reason: str) -> Optional[EnrichedAttendanceRecord]:
        try:
            target_record = await self.redis_client.get_attendance_record_by_id(attendance_id, student_school_number)
            if not target_record: return None
            
            target_record.is_attended = False
            target_record.fail_reason = reason
            
            await self.redis_client.update_attendance_record(target_record)
            enriched_list = await self._enrich_records_with_user_data([target_record])
            return enriched_list[0] if enriched_list else None
        except Exception as e:
            logger.error(f"Error failing student {student_school_number}.", exc_info=True)
            raise ServiceError("A server error occurred while updating student status.") from e

    async def get_historical_attendances(self, teacher: User) -> List[Attendance]:
        return await self.db_client.get_attendances(teacher.user_school_number)

    async def get_historical_attendance_records(self, attendance_id: UUID) -> List[EnrichedAttendanceRecord]:
        records = await self.db_client.get_attendance_records(attendance_id)
        return await self._enrich_records_with_user_data(records)

    async def add_student_to_historical_attendance(self, attendance_id: UUID, student: User, is_attended: bool, reason: Optional[str] = None):
        try:
            if not await self.db_client.get_attendance_by_id(attendance_id):
                raise ServiceError(f"Attendance session ({attendance_id}) not found in the database.")
            
            await self.db_client.add_users([student])

            new_record = AttendanceRecord(
                attendance_id=attendance_id, student_number=student.user_school_number, is_attended=is_attended,
                attendance_time=datetime.now(timezone.utc) if is_attended else None, fail_reason=reason
            )
            await self.db_client.add_attendance_records([new_record])
        except Exception as e:
            logger.error(f"Error adding student {student.user_school_number} to historical attendance.", exc_info=True)
            raise ServiceError("An error occurred while adding the student to the historical attendance.") from e

    async def accept_student_in_historical_attendance(self, attendance_id: UUID, student_school_number: str):
        try:
            logger.info(f"Marking student '{student_school_number}' as 'successful' in historical attendance ({attendance_id}).")
            await self.db_client.accept_historical_attendance_record(attendance_id, student_school_number)
            logger.info(f"Successfully updated student '{student_school_number}' in historical attendance.")
        except Exception as e:
            logger.error(f"Error updating historical attendance record.", exc_info=True)
            raise ServiceError("An error occurred while updating the student's status in historical attendance.") from e

    async def fail_student_in_historical_attendance(self, attendance_id: UUID, student_school_number: str, reason: str):
        try:
            logger.info(f"Marking student '{student_school_number}' as 'failed' in historical attendance ({attendance_id}). Reason: {reason}")
            await self.db_client.fail_historical_attendance_record(attendance_id, student_school_number, reason)
            logger.info(f"Successfully updated student '{student_school_number}' to 'failed' in historical attendance.")
        except Exception as e:
            logger.error(f"Error updating historical attendance record.", exc_info=True)
            raise ServiceError("An error occurred while updating the student's status in historical attendance.") from e

    async def delete_attendance(self, attendance_id: UUID, reason: str):
        try:
            await self.db_client.delete_attendance(attendance_id, reason)
            logger.info(f"Attendance ({attendance_id}) marked as deleted in the database.")
        except Exception as e:
            logger.error(f"Error while deleting attendance ({attendance_id}).", exc_info=True)
            raise ServiceError("An error occurred while deleting the attendance session.") from e

    async def delete_student_from_attendance(self, attendance_id: UUID, student_number: str, reason: str) -> int:
        try:
            result_str = await self.db_client.delete_attendance_record(
                attendance_id=attendance_id, student_number=student_number, reason=reason
            )
            return int(str(result_str).split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0
        except Exception as e:
            logger.error(f"Error deleting student {student_number} record.", exc_info=True)
            raise ServiceError("An error occurred while deleting the student record.") from e
