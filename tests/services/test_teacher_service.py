import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, ANY

# Test edilecek servis ve modeller
from app.backend.services.teacher_service import TeacherService, AuthorizationError, ServiceError, EnrichedAttendanceRecord
from app.backend.models.db_models import User, Attendance, AttendanceRecord
from app.backend.models.redis_models import AttendanceRedis, AttendanceRecordRedis

# --- Test Fixtures ---

@pytest.fixture
def teacher_user() -> User:
    """Creates a standard teacher user object for tests."""
    return User(user_school_number="T001", user_full_name="Dr. Ada Lovelace", role="Teacher")

@pytest.fixture
def another_teacher_user() -> User:
    """Creates a different teacher user for authorization tests."""
    return User(user_school_number="T002", user_full_name="Dr. Grace Hopper", role="Teacher")

@pytest.fixture
def student_user() -> User:
    """Creates a standard student user object for tests."""
    return User(user_school_number="S001", user_full_name="Test Student", role="Student")

@pytest.fixture
def live_attendance_session(teacher_user) -> AttendanceRedis:
    """Creates a sample live attendance session object."""
    return AttendanceRedis(
        attendance_id=uuid.uuid4(),
        teacher_school_number=teacher_user.user_school_number,
        teacher_full_name=teacher_user.user_full_name,
        lesson_name="Live Session Test",
        start_time=datetime.now(timezone.utc) - timedelta(minutes=10),
        end_time=datetime.now(timezone.utc) + timedelta(hours=1),
        security_option=1
    )

@pytest_asyncio.fixture
async def service_instance():
    """Creates a TeacherService instance with mocked clients for each test."""
    mock_redis_client = AsyncMock()
    mock_db_client = AsyncMock()
    service = TeacherService(redis_client=mock_redis_client, db_client=mock_db_client)
    return service, mock_redis_client, mock_db_client

# --- Test Scenarios ---

@pytest.mark.asyncio
class TestTeacherService:

    # --- Live Attendance Management Tests ---

    async def test_start_attendance_success(self, service_instance, teacher_user):
        """Scenario: Successfully starts a new attendance session."""
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session_of_teacher.return_value = None
        
        await service.start_attendance(
            teacher=teacher_user, lesson_name="Software Architecture", ip_address="127.0.0.1",
            start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc) + timedelta(hours=1), security_option=1
        )

        mock_redis_client.save_attendance_session.assert_called_once()
        saved_session = mock_redis_client.save_attendance_session.call_args[0][0]
        assert isinstance(saved_session, AttendanceRedis)

    async def test_start_attendance_when_already_active_raises_error(self, service_instance, teacher_user, live_attendance_session):
        """Scenario: Raises a ServiceError when trying to start a new session while another one is already active."""
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session_of_teacher.return_value = live_attendance_session
        
        with pytest.raises(ServiceError, match="You already have an active attendance session. Please end it first."):
            await service.start_attendance(
                teacher=teacher_user, lesson_name="New Lesson", ip_address="127.0.0.1",
                start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc) + timedelta(hours=1), security_option=1
            )
        
        mock_redis_client.save_attendance_session.assert_not_called()

    async def test_finish_attendance_updates_end_time(self, service_instance, teacher_user, live_attendance_session):
        """
        Scenario: Finishing an attendance session updates its end_time to now
        and saves it back to Redis, making it eligible for the cron job.
        """
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session.return_value = live_attendance_session

        time_before_finish = datetime.now(timezone.utc)
        await service.finish_attendance(teacher_user, live_attendance_session.attendance_id)

        mock_redis_client.delete_attendance_session.assert_not_called()
        mock_redis_client.save_attendance_session.assert_called_once()
        
        updated_session = mock_redis_client.save_attendance_session.call_args[0][0]
        
        assert isinstance(updated_session, AttendanceRedis)
        assert updated_session.end_time >= time_before_finish

    async def test_finish_attendance_not_owner_raises_auth_error(self, service_instance, another_teacher_user, live_attendance_session):
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session.return_value = live_attendance_session

        with pytest.raises(AuthorizationError):
            await service.finish_attendance(another_teacher_user, live_attendance_session.attendance_id)

    async def test_get_live_attendance_by_teacher(self, service_instance, teacher_user):
        service, mock_redis_client, _ = service_instance
        await service.get_live_attendance_by_teacher(teacher_user)
        mock_redis_client.get_attendance_session_of_teacher.assert_called_once_with(teacher_user.user_school_number)

    # --- Live Record Management ---

    async def test_get_live_attendance_records(self, service_instance, student_user):
        service, mock_redis_client, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        redis_record = AttendanceRecordRedis(attendance_id=attendance_id, student_number=student_user.user_school_number, student_full_name=student_user.user_full_name)
        mock_redis_client.get_attendance_records.return_value = [redis_record]

        result = await service.get_live_attendance_records(attendance_id)

        mock_db_client.get_users.assert_not_called()
        assert len(result) == 1
        assert isinstance(result[0], EnrichedAttendanceRecord)

    async def test_accept_student_in_live_attendance(self, service_instance, student_user):
        service, mock_redis_client, _ = service_instance
        attendance_id = uuid.uuid4()
        record = AttendanceRecordRedis(attendance_id=attendance_id, student_number=student_user.user_school_number, student_full_name=student_user.user_full_name, is_attended=False)
        mock_redis_client.get_attendance_record_by_id.return_value = record
        
        await service.accept_student_attendance(attendance_id, student_user.user_school_number)
        
        mock_redis_client.update_attendance_record.assert_called_once()
        updated_record = mock_redis_client.update_attendance_record.call_args[0][0]
        assert updated_record.is_attended is True

    # --- Historical Attendance Management ---

    async def test_get_historical_attendances(self, service_instance, teacher_user):
        service, _, mock_db_client = service_instance
        await service.get_historical_attendances(teacher_user)
        mock_db_client.get_attendances.assert_called_once_with(teacher_user.user_school_number)

    async def test_get_historical_attendance_records(self, service_instance, student_user):
        service, _, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        db_record = AttendanceRecord(attendance_id=attendance_id, student_number=student_user.user_school_number)
        mock_db_client.get_attendance_records.return_value = [db_record]
        mock_db_client.get_users.return_value = [student_user]
        
        result = await service.get_historical_attendance_records(attendance_id)
        
        assert len(result) == 1
        assert isinstance(result[0], EnrichedAttendanceRecord)

    async def test_add_student_to_historical_attendance(self, service_instance, student_user):
        service, _, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        mock_db_client.get_attendance_by_id.return_value = Attendance(attendance_id=attendance_id, teacher_school_number="any", lesson_name="any", start_time=datetime.now(), end_time=datetime.now(), security_option=1)
        
        await service.add_student_to_historical_attendance(attendance_id, student_user, is_attended=True)
        
        mock_db_client.add_users.assert_called_once_with([student_user])
        mock_db_client.add_attendance_records.assert_called_once()

    async def test_accept_student_in_historical_attendance(self, service_instance, student_user):
        service, _, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        await service.accept_student_in_historical_attendance(attendance_id, student_user.user_school_number)
        mock_db_client.accept_historical_attendance_record.assert_called_once_with(attendance_id, student_user.user_school_number)

    async def test_fail_student_in_historical_attendance(self, service_instance, student_user):
        service, _, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        reason = "Marked absent"
        await service.fail_student_in_historical_attendance(attendance_id, student_user.user_school_number, reason)
        mock_db_client.fail_historical_attendance_record.assert_called_once_with(attendance_id, student_user.user_school_number, reason)

    async def test_delete_student_from_attendance(self, service_instance, student_user):
        service, _, mock_db_client = service_instance
        attendance_id = uuid.uuid4()
        reason = "Cleanup"
        mock_db_client.delete_attendance_record.return_value = "UPDATE 1"
        result = await service.delete_student_from_attendance(attendance_id, student_user.user_school_number, reason)
        mock_db_client.delete_attendance_record.assert_called_once_with(attendance_id=attendance_id, student_number=student_user.user_school_number, reason=reason)
        assert result == 1
