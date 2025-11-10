import pytest
import pytest_asyncio
import uuid
import asyncpg
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import redis.asyncio as redis

# Test edilecek görevler ve modeller
from app.backend.tasks.cron import unified_persistence_task, check_face_verification_results_task
from app.backend.models.db_models import User, Attendance, AttendanceRecord
from app.backend.models.redis_models import AttendanceRedis, AttendanceRecordRedis
from app.backend.db.redis_client import RedisClient
from app.backend.db.db_client import AsyncPostgresClient
from app.backend.tools.face_verifier import VerificationError

# ----- Fikstürler (Gerçek DB ve Redis Bağlantıları ile Entegrasyon Testleri için) -----

@pytest_asyncio.fixture(scope="function")
async def db_pool():
    local_dsn = "postgresql://attn_user:your_strong_password_here@localhost:5433/attn_db"
    try:
        pool = await asyncpg.create_pool(dsn=local_dsn)
        yield pool
        await pool.close()
    except Exception as e:
        pytest.fail(f"Test veritabanına bağlanılamadı. Docker çalışıyor mu? Hata: {e}")

@pytest_asyncio.fixture(scope="function")
async def db_client(db_pool):
    client = AsyncPostgresClient(pool=db_pool)
    async with client._pool.acquire() as connection:
        await connection.execute("TRUNCATE TABLE Attendances, AttendanceRecords, Users RESTART IDENTITY CASCADE;")
    yield client

@pytest_asyncio.fixture(scope="function")
async def redis_pool():
    local_redis_url = "redis://localhost:6379/1"
    try:
        pool = redis.ConnectionPool.from_url(local_redis_url, decode_responses=True)
        client = redis.Redis(connection_pool=pool)
        await client.ping()
        await client.flushdb()
        yield pool
        await client.flushdb()
        await client.aclose()
    except Exception as e:
        pytest.fail(f"Test Redis sunucusuna bağlanılamadı. Docker çalışıyor mu? Hata: {e}")

@pytest.fixture
def redis_client(redis_pool):
    return RedisClient(pool=redis_pool)


# ===== Yardımcı Fonksiyonlar =====

def create_attendance_redis(teacher_school_number: str, teacher_full_name: str, lesson_name: str, end_time: datetime) -> AttendanceRedis:
    return AttendanceRedis(
        attendance_id=uuid.uuid4(),
        teacher_school_number=teacher_school_number,
        teacher_full_name=teacher_full_name,
        lesson_name=lesson_name,
        start_time=end_time - timedelta(hours=1),
        end_time=end_time,
        security_option=1
    )

def create_student_record_redis(attendance_id: uuid.UUID, student_number: str, student_full_name: str) -> AttendanceRecordRedis:
    return AttendanceRecordRedis(attendance_id=attendance_id, student_number=student_number, student_full_name=student_full_name, is_attended=True, attendance_time=datetime.now(timezone.utc))

# ===== Entegrasyon Testleri =====

@pytest.mark.asyncio
async def test_unified_persistence_task_integration(redis_client: RedisClient, db_client: AsyncPostgresClient):
    teacher_school_number, teacher_full_name = "T-101", "Dr. Integration"
    student1_number, student1_name = "S-201", "Student Alpha"
    expired_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    attendance_redis = create_attendance_redis(teacher_school_number, teacher_full_name, "Integration Lesson", expired_time)
    student_record1 = create_student_record_redis(attendance_redis.attendance_id, student1_number, student1_name)
    
    await redis_client.save_attendance_session(attendance_redis)
    await redis_client.add_attendance_record(student_record1)
    
    await unified_persistence_task(redis_client, db_client)
    
    db_users = await db_client.get_users([teacher_school_number, student1_number])
    db_attendance = await db_client.get_attendance_by_id(attendance_redis.attendance_id)
    db_records = await db_client.get_attendance_records(attendance_redis.attendance_id)
    
    assert len(db_users) == 2
    assert db_attendance is not None
    assert len(db_records) == 1
    assert await redis_client.get_attendance_session(attendance_redis.attendance_id) is None

