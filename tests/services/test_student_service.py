import pytest
import pytest_asyncio
import uuid
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

# Test edilecek servis ve modeller
from app.backend.services.student_service import StudentService, ServiceError
from app.backend.models.db_models import User
from app.backend.models.redis_models import UserSessionRedis, AttendanceRedis, AttendanceRecordRedis
from app.backend.tools.face_verifier import VerificationError

# --- Test Fikstürleri ---

@pytest.fixture
def student_user() -> User:
    """Testler için standart bir öğrenci nesnesi oluşturur."""
    return User(user_school_number="S001", user_full_name="Test Student", role="Student")

@pytest.fixture
def active_attendance_session() -> AttendanceRedis:
    """Testler için standart, süresi dolmamış bir yoklama oturumu oluşturur."""
    return AttendanceRedis(
        attendance_id=uuid.uuid4(),
        teacher_school_number="T001",
        teacher_full_name="Dr. Ada Lovelace",
        lesson_name="Active Lesson",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc) + timedelta(hours=1),
        security_option=1,
        ip_address="192.168.1.100"
    )

@pytest.fixture
def expired_attendance_session() -> AttendanceRedis:
    """Testler için standart, süresi dolmuş bir yoklama oturumu oluşturur."""
    end_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    return AttendanceRedis(
        attendance_id=uuid.uuid4(),
        teacher_school_number="T001",
        teacher_full_name="Dr. Ada Lovelace",
        lesson_name="Expired Lesson",
        start_time=end_time - timedelta(hours=1),
        end_time=end_time,
        security_option=1
    )

@pytest.fixture
def student_user_session(student_user) -> UserSessionRedis:
    """Yüz tanıma için geçerli, image_url'i olan bir kullanıcı oturumu."""
    return UserSessionRedis(
        user_data=student_user,
        session_id=uuid.uuid4(),
        session_start_time=datetime.now(timezone.utc),
        session_end_time=datetime.now(timezone.utc) + timedelta(hours=1),
        image_url="http://example.com/image.jpg"
    )

@pytest.fixture
def dummy_image_bytes() -> bytes:
    """Yüz tanıma için geçerli bir base64 byte dizisi."""
    return base64.b64decode(b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

@pytest_asyncio.fixture
async def service_instance():
    """Her test için mock'lanmış client'lar ile bir StudentService instance'ı oluşturur."""
    mock_redis_client = AsyncMock()
    mock_db_client = AsyncMock()
    service = StudentService(redis_client=mock_redis_client, db_client=mock_db_client)
    return service, mock_redis_client, mock_db_client


# --- Test Senaryoları ---

@pytest.mark.asyncio
class TestStudentService:

    # --- find_active_sessions_by_name Metodu Testleri ---
    
    async def test_find_active_sessions_filters_expired_sessions(self, service_instance, active_attendance_session, expired_attendance_session):
        """Senaryo: Ders arandığında, süresi dolmuş olanların filtrelendiğini doğrular."""
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_sessions_by_name.return_value = [
            active_attendance_session,
            expired_attendance_session
        ]
        
        result = await service.find_active_sessions_by_name("Mixed Lessons", "Dr. Ada Lovelace")
        
        assert len(result) == 1
        assert result[0].attendance_id == active_attendance_session.attendance_id

    # --- attend_to_attendance Metodu Testleri ---

    async def test_attend_to_expired_session_raises_error(self, service_instance, student_user, expired_attendance_session):
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session.return_value = expired_attendance_session
        
        with pytest.raises(ServiceError, match="This attendance session has already ended."):
            await service.attend_to_attendance(student_user, expired_attendance_session.attendance_id)

    async def test_attend_sec_1_success(self, service_instance, student_user, active_attendance_session):
        """Senaryo (Seviye 1): Güvenlik olmadığında katılım direkt başarılı olur."""
        service, mock_redis_client, _ = service_instance
        active_attendance_session.security_option = 1
        mock_redis_client.get_attendance_session.return_value = active_attendance_session
        mock_redis_client.get_attendance_record_by_id.return_value = None

        record = await service.attend_to_attendance(student_user, active_attendance_session.attendance_id)
        
        assert record.is_attended is True
        assert record.fail_reason is None
        mock_redis_client.add_attendance_record.assert_called_once()
        
    async def test_attend_already_attended_raises_error(self, service_instance, student_user, active_attendance_session):
        service, mock_redis_client, _ = service_instance
        mock_redis_client.get_attendance_session.return_value = active_attendance_session
        existing_record = AttendanceRecordRedis(attendance_id=active_attendance_session.attendance_id, student_number=student_user.user_school_number, student_full_name=student_user.user_full_name, is_attended=True)
        mock_redis_client.get_attendance_record_by_id.return_value = existing_record
        
        with pytest.raises(ServiceError, match="You have already successfully joined this session."):
            await service.attend_to_attendance(student_user, active_attendance_session.attendance_id)

    @patch('app.backend.services.student_service.verify_wifi', return_value=False)
    async def test_attend_sec_2_wifi_fails(self, mock_wifi, service_instance, student_user, active_attendance_session):
        """Senaryo (Seviye 2): Wi-Fi kontrolü başarısız olur."""
        service, mock_redis_client, _ = service_instance
        active_attendance_session.security_option = 2
        mock_redis_client.get_attendance_session.return_value = active_attendance_session
        mock_redis_client.get_attendance_record_by_id.return_value = None

        record = await service.attend_to_attendance(student_user, active_attendance_session.attendance_id, student_ip="1.2.3.4")

        assert record.is_attended is False
        assert record.fail_reason == "WIFI_FAILED"

    # ================================================================= #
    # --- REFACTOR EDİLMİŞ TEST ---
    # ================================================================= #
    @patch('app.backend.services.student_service.AksisClient.get_profile_image_base64', new_callable=AsyncMock)
    @patch('app.backend.services.student_service.submit_face_verification_job', new_callable=AsyncMock) # DEĞİŞİKLİK: Yeni fonksiyonu patch'liyoruz
    @patch('app.backend.services.student_service.verify_wifi', return_value=True)
    async def test_attend_sec_3_webhook_flow_is_pending(self, mock_wifi, mock_face_submit, mock_aksis, service_instance, student_user, active_attendance_session, student_user_session, dummy_image_bytes):
        """Senaryo (Seviye 3): Yüz tanıma işi webhook için başarıyla gönderildiğinde durum 'beklemede' olur."""
        service, mock_redis_client, _ = service_instance
        active_attendance_session.security_option = 3
        mock_redis_client.get_attendance_session.return_value = active_attendance_session
        mock_redis_client.get_attendance_record_by_id.return_value = None
        mock_redis_client.get_user_session.return_value = student_user_session
        mock_aksis.return_value = base64.b64encode(dummy_image_bytes).decode('utf-8')
        # DEĞİŞİKLİK: submit_face_verification_job artık bir şey döndürmüyor (veya "SUBMITTED" gibi basit bir string)
        mock_face_submit.return_value = "SUBMITTED"

        record = await service.attend_to_attendance(
            student_user, active_attendance_session.attendance_id, student_ip="192.168.1.100", normal_image_bytes=dummy_image_bytes
        )

        assert record.is_attended is False
        assert record.fail_reason == "FACE_RECOGNITION_PENDING"
        
        # DEĞİŞİKLİK: Artık kuyruğa ekleme fonksiyonu çağrılmıyor.
        mock_redis_client.add_user_to_face_verification_queue.assert_not_called()
        # Bunun yerine, submit işinin doğru parametrelerle çağrıldığını kontrol edebiliriz.
        mock_face_submit.assert_awaited_once()

    # --- get_my_attendance_status Metodu Testleri ---

    async def test_get_my_attendance_status_record_found(self, service_instance, student_user, active_attendance_session):
        """Senaryo: Öğrencinin katılım kaydı aktif bir derste bulunduğunda doğru şekilde dönmeli."""
        service, mock_redis_client, _ = service_instance
        attendance_id = active_attendance_session.attendance_id
        
        # YENİ: Oturumun aktif olduğunu mock'la
        mock_redis_client.get_attendance_session.return_value = active_attendance_session
        
        my_record = AttendanceRecordRedis(
            attendance_id=attendance_id, student_number=student_user.user_school_number,
            student_full_name=student_user.user_full_name,
            is_attended=False, fail_reason="FACE_RECOGNITION_PENDING"
        )
        mock_redis_client.get_attendance_record_by_id.return_value = my_record
        
        retrieved_record = await service.get_my_attendance_status(attendance_id, student_user)
        
        mock_redis_client.get_attendance_record_by_id.assert_called_once_with(
            attendance_id=attendance_id, student_number=student_user.user_school_number
        )
        assert retrieved_record is not None
        assert retrieved_record.fail_reason == "FACE_RECOGNITION_PENDING"

    # --- YENİ EKLENEN TEST ---
    async def test_get_my_attendance_status_for_expired_session_raises_error(self, service_instance, student_user, expired_attendance_session):
        """Senaryo: Süresi dolmuş bir ders için durum sorgulandığında hata fırlatılmalı."""
        service, mock_redis_client, _ = service_instance
        # Süresi dolmuş oturumu döndürecek şekilde mock'la
        mock_redis_client.get_attendance_session.return_value = expired_attendance_session
        
        with pytest.raises(ServiceError, match="This attendance session has already ended."):
            await service.get_my_attendance_status(expired_attendance_session.attendance_id, student_user)
        
        # Hata fırlattığı için, öğrenci kaydını sorgulama metodunun hiç çağrılmadığını doğrula
        mock_redis_client.get_attendance_record_by_id.assert_not_called()

