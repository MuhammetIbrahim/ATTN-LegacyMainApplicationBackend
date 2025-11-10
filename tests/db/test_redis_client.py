import pytest
import pytest_asyncio
import redis.asyncio as redis
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# --- Test edilecek modeller ve istemci ---
from app.backend.models.db_models import User
from app.backend.models.redis_models import UserSessionRedis, AttendanceRedis, AttendanceRecordRedis
from app.backend.db.redis_client import RedisClient

# ----- Test Redis Bağlantı Detayları -----
TEST_REDIS_URL = "redis://localhost:6379/0"

@pytest_asyncio.fixture(scope="function")
async def redis_pool():
    """Her test fonksiyonu için bir Redis bağlantı havuzu oluşturur."""
    pool = redis.ConnectionPool.from_url(TEST_REDIS_URL, decode_responses=True)
    client = redis.Redis(connection_pool=pool)
    await client.flushdb() # Her test için temiz bir başlangıç sağla
    yield pool
    # Test sonrası temizlik
    await client.flushdb()
    await client.aclose()


# ===== Yardımcı Fonksiyonlar & Örnek Veriler =====

def create_sample_user_redis(school_number: str = "T001", role: str = "Teacher") -> UserSessionRedis:
    user = User(user_school_number=school_number, user_full_name="Test User", role=role)
    return UserSessionRedis(
        user_data=user,
        session_id=uuid.uuid4(),
        session_start_time=datetime.now(timezone.utc),
        session_end_time=datetime.now(timezone.utc) + timedelta(minutes=30)
    )

def create_sample_attendance_redis(
    teacher_school_number: str = "T001",
    teacher_full_name: str = "Dr. Ada Lovelace",
    lesson_name: str = "Calculus 101",
    end_time: datetime = None
) -> AttendanceRedis:
    if end_time is None:
        end_time = datetime.now(timezone.utc) + timedelta(hours=1)
    
    return AttendanceRedis(
        attendance_id=uuid.uuid4(),
        teacher_school_number=teacher_school_number,
        teacher_full_name=teacher_full_name,
        lesson_name=lesson_name,
        start_time=datetime.now(timezone.utc),
        end_time=end_time,
        security_option=1
    )

def create_sample_attendance_record_redis(
    attendance_id: uuid.UUID,
    student_number: str = "S001",
    student_full_name: str = "Test Student"
) -> AttendanceRecordRedis:
    return AttendanceRecordRedis(
        attendance_id=attendance_id,
        student_number=student_number,
        student_full_name=student_full_name,
        is_attended=True,
        attendance_time=datetime.now(timezone.utc)
    )


# ===== Test Senaryoları =====

@pytest.mark.asyncio
async def test_user_session_management(redis_pool):
    """Senaryo: Kullanıcı oturumunun yaşam döngüsünü test eder (kaydet, al, sil)."""
    client = RedisClient(pool=redis_pool)
    user_session = create_sample_user_redis()
    user_school_number = user_session.user_data.user_school_number
    ttl_seconds = 2

    await client.save_user_session(user_session, ttl=ttl_seconds)
    retrieved_session = await client.get_user_session(user_school_number)
    assert retrieved_session is not None
    
    await asyncio.sleep(ttl_seconds + 1)
    assert await client.get_user_session(user_school_number) is None

    await client.save_user_session(user_session, ttl=10)
    assert await client.get_user_session(user_school_number) is not None
    await client.delete_user_session(user_school_number)
    assert await client.get_user_session(user_school_number) is None


@pytest.mark.asyncio
async def test_save_and_get_attendance_session(redis_pool):
    client = RedisClient(pool=redis_pool)
    attendance_session = create_sample_attendance_redis()
    await client.save_attendance_session(attendance_session)
    retrieved = await client.get_attendance_session(attendance_session.attendance_id)
    assert retrieved is not None
    assert retrieved.model_dump() == attendance_session.model_dump()

@pytest.mark.asyncio
async def test_delete_attendance_session_removes_all_data(redis_pool):
    client = RedisClient(pool=redis_pool)
    attendance_session = create_sample_attendance_redis()
    await client.save_attendance_session(attendance_session)
    await client.delete_attendance_session(attendance_session)
    assert await client.get_attendance_session(attendance_session.attendance_id) is None
    
    raw_redis_client = redis.Redis(connection_pool=redis_pool, decode_responses=True)
    index_key_by_name = f"attendance_index:name:{attendance_session.lesson_name}:{attendance_session.teacher_full_name}"
    index_key_by_teacher = f"attendance_index:teacher:{attendance_session.teacher_school_number}"
    assert not await raw_redis_client.exists(index_key_by_name)
    assert not await raw_redis_client.exists(index_key_by_teacher)

@pytest.mark.asyncio
async def test_get_attendance_sessions_by_name(redis_pool):
    client = RedisClient(pool=redis_pool)
    session1 = create_sample_attendance_redis(lesson_name="Calculus", teacher_full_name="Dr. Turing")
    session2 = create_sample_attendance_redis(lesson_name="Calculus", teacher_full_name="Dr. Turing")
    await client.save_attendance_session(session1)
    await client.save_attendance_session(session2)
    found_sessions = await client.get_attendance_sessions_by_name("Calculus", "Dr. Turing")
    assert len(found_sessions) == 2

@pytest.mark.asyncio
async def test_get_attendance_session_of_teacher_with_active_session(redis_pool):
    client = RedisClient(pool=redis_pool)
    teacher_id = "T_ACTIVE_01"
    active_session = create_sample_attendance_redis(teacher_school_number=teacher_id, end_time=datetime.now(timezone.utc) + timedelta(minutes=30))
    await client.save_attendance_session(active_session)
    found_session = await client.get_attendance_session_of_teacher(teacher_id)
    assert found_session is not None
    assert found_session.attendance_id == active_session.attendance_id

@pytest.mark.asyncio
async def test_get_attendance_session_of_teacher_with_expired_session(redis_pool):
    client = RedisClient(pool=redis_pool)
    teacher_id = "T_EXPIRED_01"
    expired_session = create_sample_attendance_redis(teacher_school_number=teacher_id, end_time=datetime.now(timezone.utc) - timedelta(minutes=5))
    await client.save_attendance_session(expired_session)
    found_session = await client.get_attendance_session_of_teacher(teacher_id)
    assert found_session is None

@pytest.mark.asyncio
async def test_attendance_record_management(redis_pool):
    client = RedisClient(pool=redis_pool)
    att_id = uuid.uuid4()
    record = create_sample_attendance_record_redis(att_id, "S001")
    await client.add_attendance_record(record)
    retrieved = await client.get_attendance_record_by_id(att_id, "S001")
    assert retrieved is not None
    retrieved.is_attended = False
    await client.update_attendance_record(retrieved)
    updated = await client.get_attendance_record_by_id(att_id, "S001")
    assert updated.is_attended is False



@pytest.mark.asyncio
async def test_webhook_verification_mapping(redis_pool):
    """
    Senaryo: Webhook için oluşturulan geçici doğrulama eşleşmesinin yaşam döngüsünü test eder.
    (map_verification_to_user, get_user_and_attendance_for_verification, delete_verification_mapping)
    """
    # 1. Hazırlık (Setup)
    client = RedisClient(pool=redis_pool)
    verification_id = str(uuid.uuid4())
    user_school_number = "S12345"
    attendance_id = str(uuid.uuid4())

    # 2. Test: Eşleşmeyi kaydet ve doğrula
    # `map_verification_to_user` fonksiyonunu çağırarak veriyi kaydet
    await client.map_verification_to_user(verification_id, user_school_number, attendance_id)

    # `get_user_and_attendance_for_verification` ile veriyi geri al
    retrieved_data = await client.get_user_and_attendance_for_verification(verification_id)

    # Dönen verinin doğru olduğunu teyit et
    assert retrieved_data is not None
    assert retrieved_data["user_school_number"] == user_school_number
    assert retrieved_data["attendance_id"] == attendance_id

    # 3. Test: Eşleşmeyi sil ve silindiğini doğrula
    # `delete_verification_mapping` fonksiyonunu çağırarak veriyi sil
    await client.delete_verification_mapping(verification_id)

    # Verinin artık mevcut olmadığını teyit et
    retrieved_data_after_delete = await client.get_user_and_attendance_for_verification(verification_id)
    assert retrieved_data_after_delete is None