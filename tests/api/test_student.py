import pytest
import pytest_asyncio
import httpx
import uuid
import asyncio
import base64
from datetime import datetime, timezone, timedelta

# Test ortamı için gerekli istemcileri ve havuzları import edelim
from app.backend.db.db_client import AsyncPostgresClient
from app.backend.db.redis_client import RedisClient
from tests.db.test_db_client import db_pool
from tests.db.test_redis_client import redis_pool

# Test verisi oluşturmak için modeller
from app.backend.models.db_models import User
from app.backend.api.schemas.attendence import AttendanceResponse
from app.backend.api.schemas.attendence_record import AttendanceRecordResponse

# --- Test Ayarları ---
API_BASE_URL = "http://localhost:8001/api/v1"
TEACHER_USERNAME = "demo_teacher_1"
TEACHER_PASSWORD = "password"
STUDENT_USERNAME = "demo_student_1"
STUDENT_PASSWORD = "password"
TEACHER_FULL_NAME = "Demo Teacher 1"
SIMULATED_STUDENT_IP = "192.168.1.50"

# --- Fikstürler (Test Altyapısı) ---

@pytest.fixture(scope="module")
def anyio_backend():
    return 'asyncio'

async def get_auth_client(username, password) -> httpx.AsyncClient:
    """Verilen bilgilerle giriş yapar ve yetkilendirme başlığına sahip bir httpx client döndürür."""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
        try:
            await asyncio.sleep(0.5) # Rate limit için kısa bekleme
            login_data = {"username": username, "password": password}
            response = await client.post("/auth/login", json=login_data)
            response.raise_for_status()
            token = f"Bearer {response.json()['token']['access_token']}"
            
            auth_client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                headers={
                    "Authorization": token,
                    "X-Forwarded-For": SIMULATED_STUDENT_IP
                }
            )
            return auth_client
        except Exception as e:
            pytest.fail(f"E2E Test için kimlik doğrulama başarısız ({username}): {e}")

@pytest_asyncio.fixture(scope="function")
async def teacher_client():
    client = await get_auth_client(TEACHER_USERNAME, TEACHER_PASSWORD)
    yield client
    await client.aclose()

@pytest_asyncio.fixture(scope="function")
async def student_client():
    client = await get_auth_client(STUDENT_USERNAME, STUDENT_PASSWORD)
    yield client
    await client.aclose()

@pytest.fixture(scope="function")
def dummy_image_bytes():
    return base64.b64decode(b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

@pytest_asyncio.fixture(autouse=True)
async def setup_api_tests(db_pool, redis_pool):
    """FIX: Her testten önce çalışır ve ortamı temizleyip test kullanıcılarını oluşturur."""
    db_client = AsyncPostgresClient(db_pool)
    redis_client = RedisClient(redis_pool)
    
    await redis_client._redis.flushdb()
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE AttendanceRecords, Attendances, Users RESTART IDENTITY CASCADE;")

    users_to_add = [
        User(user_school_number=TEACHER_USERNAME, user_full_name=TEACHER_FULL_NAME, role="Teacher"),
        User(user_school_number=STUDENT_USERNAME, user_full_name="Demo Student 1", role="Student")
    ]
    await db_client.add_users(users_to_add)
    yield


# --- Yardımcı Fonksiyonlar ---
async def create_live_attendance(client: httpx.AsyncClient, lesson_name: str, security_option: int) -> dict:
    """Testler için hızlıca canlı bir yoklama oluşturan yardımcı."""
    start_data = {
        "lesson_name": lesson_name,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "security_option": security_option
    }
    response = await client.post("/teacher/attendances", json=start_data)
    assert response.status_code == 201, f"Yoklama oluşturma başarısız: {response.text}"
    return response.json()


# --- TEST SINIFI ---

@pytest.mark.asyncio
class TestStudentE2E:

    async def test_find_sessions_success_and_not_found(self, teacher_client: httpx.AsyncClient, student_client: httpx.AsyncClient):
        """Senaryo: Aktif bir oturum başarıyla bulunur ve olmayan bir oturum için boş liste döner."""
        lesson_name = f"E2E Find Test - {uuid.uuid4()}"
        await create_live_attendance(teacher_client, lesson_name, 1)

        params_success = {"lesson_name": lesson_name, "teacher_name": TEACHER_FULL_NAME}
        # REFACTORED: Use the new endpoint
        response_success = await student_client.get("/student/sessions/find", params=params_success)
        
        assert response_success.status_code == 200
        sessions = response_success.json()
        assert len(sessions) == 1
        # REFACTORED: Validate against the new response schema
        validated_session = AttendanceResponse.model_validate(sessions[0])
        assert validated_session.lesson_name == lesson_name
        assert validated_session.teacher_full_name == TEACHER_FULL_NAME

        # Başarısız arama
        params_fail = {"lesson_name": "Olmayan Ders", "teacher_name": "Olmayan Hoca"}
        response_fail = await student_client.get("/student/sessions/find", params=params_fail)
        assert response_fail.status_code == 200
        assert response_fail.json() == []

    async def test_attend_flow_security_level_1_success(self, teacher_client, student_client):
        """Senaryo (Seviye 1): Öğrenci önce oturumu bulur, sonra başarıyla katılır."""
        lesson_name = f"E2E Seviye-1 Test - {uuid.uuid4()}"
        live_att = await create_live_attendance(teacher_client, lesson_name, 1)
        attendance_id = live_att["attendance_id"]

        response = await student_client.post(f"/student/attendances/{attendance_id}/attend")
        
        assert response.status_code == 200
        record = AttendanceRecordResponse.model_validate(response.json())
        assert record.is_attended is True

    async def test_attend_flow_security_level_2_wifi_fail(self, teacher_client, student_client):
        """Senaryo (Seviye 2): Öğrenci IP'si uyuşmadığı için katılamaz."""
        lesson_name = f"E2E Seviye-2 Fail - {uuid.uuid4()}"
        
        # Öğrencinin IP'sinden farklı bir IP ile ders başlat
        teacher_client.headers['X-Forwarded-For'] = "10.0.0.1"
        live_att = await create_live_attendance(teacher_client, lesson_name, 2)
        attendance_id = live_att["attendance_id"]

        response = await student_client.post(f"/student/attendances/{attendance_id}/attend")

        assert response.status_code == 200
        assert "WIFI_FAILED" in response.json()["fail_reason"]

    async def test_attend_flow_security_level_3_pending(self, teacher_client, student_client, dummy_image_bytes):
        """Senaryo (Seviye 3): Öğrenci resim yükler ve durumu 'beklemede' olur."""
        lesson_name = f"E2E Seviye-3 Pending - {uuid.uuid4()}"
        live_att = await create_live_attendance(teacher_client, lesson_name, 3)
        attendance_id = live_att["attendance_id"]
        
        files_data = {'normal_image': ('test.jpg', dummy_image_bytes, 'image/jpeg')}
        
        response = await student_client.post(f"/student/attendances/{attendance_id}/attend", files=files_data)
        
        assert response.status_code == 200
        record = AttendanceRecordResponse.model_validate(response.json())
        assert record.is_attended is False
        assert record.fail_reason == "FACE_RECOGNITION_PENDING"

    async def test_get_my_attendance_status(self, teacher_client, student_client):
        """Senaryo: Öğrenci bir derse katıldıktan sonra durumunu başarıyla sorgular."""
        lesson_name = f"E2E Durum Sorgulama - {uuid.uuid4()}"
        live_attendance = await create_live_attendance(teacher_client, lesson_name, 1)
        attendance_id = live_attendance["attendance_id"]

        await student_client.post(f"/student/attendances/{attendance_id}/attend")
        await asyncio.sleep(0.1)

        status_response = await student_client.get(f"/student/attendances/{attendance_id}/status")
        
        assert status_response.status_code == 200
        record = AttendanceRecordResponse.model_validate(status_response.json())
        assert str(record.attendance_id) == attendance_id
        assert record.is_attended is True
