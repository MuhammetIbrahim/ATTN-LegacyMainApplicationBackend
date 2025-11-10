import pytest
import pytest_asyncio
import httpx
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
import json

# Test ortamı için gerekli istemcileri ve havuzları import edelim
from app.backend.db.db_client import AsyncPostgresClient
from app.backend.db.redis_client import RedisClient
from tests.db.test_db_client import db_pool
from tests.db.test_redis_client import redis_pool

# Test verisi oluşturmak için modeller
from app.backend.models.db_models import User, Attendance, AttendanceRecord
from app.backend.models.redis_models import AttendanceRecordRedis

# --- Test Ayarları ---
API_BASE_URL = "http://localhost:8001/api/v1"
TEACHER_USERNAME = "demo_teacher_1"
TEACHER_PASSWORD = "password"
OTHER_TEACHER_USERNAME = "demo_teacher_2"
STUDENT_SCHOOL_NUMBER = "demo_student_1"
NEW_STUDENT_SCHOOL_NUMBER = "S-MANUAL-01"


# --- Fikstürler (Test Altyapısı) ---

@pytest.fixture(scope="module")
def anyio_backend():
    return 'asyncio'

@pytest_asyncio.fixture(scope="function")
async def teacher_client():
    """Ana öğretmen için yetkilendirilmiş bir httpx istemcisi oluşturur."""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
        try:
            # FIX: Increase sleep to avoid rate limiting issues in parallel tests
            await asyncio.sleep(15) 
            login_data = {"username": TEACHER_USERNAME, "password": TEACHER_PASSWORD}
            response = await client.post("/auth/login", json=login_data)
            response.raise_for_status()
            token = f"Bearer {response.json()['token']['access_token']}"
            client.headers["Authorization"] = token
            yield client
        except Exception as e:
            pytest.fail(f"E2E Test Başlatılamadı: '{TEACHER_USERNAME}' girişi başarısız. Hata: {e}")

@pytest_asyncio.fixture(scope="function")
async def other_teacher_client():
    """İkinci öğretmen için yetkilendirilmiş bir httpx istemcisi oluşturur."""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30) as client:
        try:
            # FIX: Increase sleep to avoid rate limiting issues in parallel tests
            await asyncio.sleep(15)
            login_data = {"username": OTHER_TEACHER_USERNAME, "password": TEACHER_PASSWORD}
            response = await client.post("/auth/login", json=login_data)
            response.raise_for_status()
            token = f"Bearer {response.json()['token']['access_token']}"
            client.headers["Authorization"] = token
            yield client
        except Exception as e:
            pytest.fail(f"E2E Test Başlatılamadı: '{OTHER_TEACHER_USERNAME}' girişi başarısız. Hata: {e}")

@pytest_asyncio.fixture(autouse=True)
async def setup_api_tests(db_pool, redis_pool):
    """Her testten önce çalışır ve ortamı temizleyip test kullanıcılarını oluşturur."""
    db_client = AsyncPostgresClient(db_pool)
    redis_client = RedisClient(redis_pool)
    
    await redis_client._redis.flushdb()
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE AttendanceRecords, Attendances, Users RESTART IDENTITY CASCADE;")

    users_to_add = [
        User(user_school_number=TEACHER_USERNAME, user_full_name="Demo Teacher 1", role="Teacher"),
        User(user_school_number=OTHER_TEACHER_USERNAME, user_full_name="Demo Teacher 2", role="Teacher"),
        User(user_school_number=STUDENT_SCHOOL_NUMBER, user_full_name="Demo Student 1", role="Student")
    ]
    await db_client.add_users(users_to_add)
    yield

# --- Yardımcı Fonksiyonlar ---
async def create_live_attendance(client: httpx.AsyncClient, lesson_name="Test Dersi") -> dict:
    """Testler için hızlıca canlı bir yoklama oluşturan yardımcı."""
    start_data = {
        "lesson_name": lesson_name,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "security_option": 1
    }
    response = await client.post("/teacher/attendances", json=start_data)
    assert response.status_code == 201, f"Yoklama oluşturma başarısız: {response.text}"
    return response.json()

async def create_historical_attendance(db_client: AsyncPostgresClient, teacher_id: str, lesson_name="Geçmiş Ders") -> Attendance:
    """Testler için hızlıca veritabanına geçmiş bir yoklama ekler."""
    att = Attendance(
        attendance_id=uuid.uuid4(),
        teacher_school_number=teacher_id,
        lesson_name=lesson_name,
        start_time=datetime.now(timezone.utc) - timedelta(hours=1),
        end_time=datetime.now(timezone.utc) - timedelta(minutes=30),
        security_option=1
    )
    await db_client.add_attendances([att])
    return att

# --- TEST SINIFLARI ---

@pytest.mark.asyncio
class TestAttendanceSessionAPI:
    """Yoklama Oturumu Yönetimi (/teacher/attendances) endpoint'lerini test eder."""

    async def test_start_attendance_success(self, teacher_client: httpx.AsyncClient):
        response_json = await create_live_attendance(teacher_client, "Başarılı Ders")
        assert "attendance_id" in response_json
        assert response_json["lesson_name"] == "Başarılı Ders"

    async def test_start_attendance_when_already_active_fails(self, teacher_client: httpx.AsyncClient):
        await create_live_attendance(teacher_client)
        response = await teacher_client.post("/teacher/attendances", json={
            "lesson_name": "İkinci Ders",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "security_option": 1
        })
        assert response.status_code == 400
        assert "already have an active" in response.json()["detail"]

    async def test_finish_attendance(self, teacher_client: httpx.AsyncClient):
        created_att = await create_live_attendance(teacher_client)
        attendance_id = created_att["attendance_id"]
        response = await teacher_client.post(f"/teacher/attendances/{attendance_id}/finish")
        assert response.status_code == 204
        response_live = await teacher_client.get("/teacher/attendances/live")
        assert response_live.status_code == 200
        assert response_live.json() is None

    async def test_get_live_attendance(self, teacher_client: httpx.AsyncClient):
        response = await teacher_client.get("/teacher/attendances/live")
        assert response.status_code == 200 and response.json() is None
        created_att = await create_live_attendance(teacher_client)
        response = await teacher_client.get("/teacher/attendances/live")
        assert response.status_code == 200
        live_session = response.json()
        assert live_session is not None
        assert live_session["attendance_id"] == created_att["attendance_id"]

    async def test_get_historical_attendances(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        await create_historical_attendance(db_client, TEACHER_USERNAME)
        response = await teacher_client.get("/teacher/attendances/historical")
        assert response.status_code == 200
        historical_lessons = response.json()
        assert len(historical_lessons) == 1
        assert historical_lessons[0]["teacher_school_number"] == TEACHER_USERNAME


@pytest.mark.asyncio
class TestAttendanceRecordAPI:
    """Yoklama Kaydı Yönetimi (/teacher/attendances/{id}/records) endpoint'lerini test eder."""

    async def test_get_live_records(self, teacher_client: httpx.AsyncClient, redis_pool):
        created_att = await create_live_attendance(teacher_client)
        attendance_id = uuid.UUID(created_att["attendance_id"])
        redis_client = RedisClient(redis_pool)
        record_to_add = AttendanceRecordRedis(
            attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, student_full_name="Demo Student 1", is_attended=False
        )
        await redis_client.add_attendance_record(record_to_add)
        await asyncio.sleep(0.1)
        response = await teacher_client.get(f"/teacher/attendances/{attendance_id}/records")
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["student"]["user_school_number"] == STUDENT_SCHOOL_NUMBER

    async def test_accept_student_in_live_attendance(self, teacher_client: httpx.AsyncClient, redis_pool):
        created_att = await create_live_attendance(teacher_client)
        attendance_id = uuid.UUID(created_att["attendance_id"])
        redis_client = RedisClient(redis_pool)
        await redis_client.add_attendance_record(AttendanceRecordRedis(
            attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, student_full_name="Demo Student 1", is_attended=False
        ))
        response = await teacher_client.post(f"/teacher/attendances/{attendance_id}/live/records/{STUDENT_SCHOOL_NUMBER}/accept")
        assert response.status_code == 200
        assert response.json()["is_attended"] is True

    async def test_get_historical_records(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        historical_att = await create_historical_attendance(db_client, TEACHER_USERNAME)
        attendance_id = historical_att.attendance_id
        await db_client.add_attendance_records([AttendanceRecord(attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, is_attended=True)])
        response = await teacher_client.get(f"/teacher/attendances/{attendance_id}/records")
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["student"]["user_school_number"] == STUDENT_SCHOOL_NUMBER

    async def test_add_student_to_historical_attendance_with_name(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        historical_att = await create_historical_attendance(db_client, TEACHER_USERNAME)
        attendance_id = historical_att.attendance_id
        student_full_name = "Manual Student Name"
        
        # FIX: Add the required 'student_full_name' to the request payload
        add_req = {
            "student_school_number": NEW_STUDENT_SCHOOL_NUMBER,
            "student_full_name": student_full_name,
            "is_attended": False,
            "reason": "Derse hiç gelmedi."
        }
        response = await teacher_client.post(f"/teacher/attendances/{attendance_id}/historical/records", json=add_req)
        assert response.status_code == 201, f"Öğrenci ekleme başarısız: {response.text}"
        
        created_users = await db_client.get_users([NEW_STUDENT_SCHOOL_NUMBER])
        assert len(created_users) == 1
        # FIX: Assert the correct name is now in the database
        assert created_users[0].user_full_name == student_full_name
        
        records = await db_client.get_attendance_records(attendance_id)
        assert len(records) == 1
        assert records[0].student_number == NEW_STUDENT_SCHOOL_NUMBER

    async def test_accept_student_in_historical_attendance(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        historical_att = await create_historical_attendance(db_client, TEACHER_USERNAME)
        attendance_id = historical_att.attendance_id
        await db_client.add_attendance_records([AttendanceRecord(attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, is_attended=False)])
        response = await teacher_client.post(f"/teacher/attendances/{attendance_id}/historical/records/{STUDENT_SCHOOL_NUMBER}/accept")
        assert response.status_code == 200
        records = await db_client.get_attendance_records(attendance_id)
        assert records[0].is_attended is True

    async def test_fail_student_in_historical_attendance(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        historical_att = await create_historical_attendance(db_client, TEACHER_USERNAME)
        attendance_id = historical_att.attendance_id
        await db_client.add_attendance_records([AttendanceRecord(attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, is_attended=True)])
        fail_req = {"reason": "Sonradan disiplin suçu işledi."}
        response = await teacher_client.post(f"/teacher/attendances/{attendance_id}/historical/records/{STUDENT_SCHOOL_NUMBER}/fail", json=fail_req)
        assert response.status_code == 200
        records = await db_client.get_attendance_records(attendance_id)
        assert records[0].is_attended is False
        assert records[0].fail_reason == fail_req["reason"]

    async def test_delete_student_from_historical_attendance(self, teacher_client: httpx.AsyncClient, db_pool):
        db_client = AsyncPostgresClient(db_pool)
        historical_att = await create_historical_attendance(db_client, TEACHER_USERNAME)
        attendance_id = historical_att.attendance_id
        await db_client.add_attendance_records([AttendanceRecord(attendance_id=attendance_id, student_number=STUDENT_SCHOOL_NUMBER, is_attended=True)])
        delete_req = {"reason": "Kayıt yanlışlıkla oluşturuldu."}
        response = await teacher_client.request(
            "DELETE",
            f"/teacher/attendances/{attendance_id}/records/{STUDENT_SCHOOL_NUMBER}",
            content=json.dumps(delete_req).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        assert response.status_code == 204
        records = await db_client.get_attendance_records(attendance_id)
        assert len(records) == 0
