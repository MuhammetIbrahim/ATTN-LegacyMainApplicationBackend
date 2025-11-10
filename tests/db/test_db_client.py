import pytest
import pytest_asyncio
import asyncpg
import uuid
from datetime import datetime, timezone
from typing import List

from app.backend.models.db_models import User, Attendance, AttendanceRecord
from app.backend.db.db_client import AsyncPostgresClient

# ----- Test Veritabanı Bağlantı Detayları -----
# DİKKAT: Bu URL'yi kendi yerel veritabanı yapılandırmanıza göre güncelleyin.
TEST_DATABASE_URL = "postgresql://attn_user:your_strong_password_here@localhost:5433/attn_db"

@pytest_asyncio.fixture(scope="function")
async def db_pool():
    """Her test fonksiyonu için bir veritabanı bağlantı havuzu oluşturur."""
    pool = None
    try:
        pool = await asyncpg.create_pool(TEST_DATABASE_URL)
        yield pool
    finally:
        if pool:
            await pool.close()

@pytest_asyncio.fixture(autouse=True)
async def clear_tables(db_pool):
    """Her testten önce tabloları temizleyerek test izolasyonu sağlar."""
    async with db_pool.acquire() as connection:
        await connection.execute("DELETE FROM AttendanceRecords;")
        await connection.execute("DELETE FROM Attendances;")
        await connection.execute("DELETE FROM Users;")

# ===== Yardımcı Fonksiyonlar & Örnek Veriler =====

def create_sample_teacher() -> User:
    """Test için örnek bir öğretmen User nesnesi oluşturur."""
    return User(user_school_number="T001", user_full_name="Teacher One", role="Teacher")

def create_sample_students(count: int = 2) -> List[User]:
    """Test için örnek öğrenci User nesnelerinden oluşan bir liste oluşturur."""
    return [User(user_school_number=f"S{i:03}", user_full_name=f"Student {i}", role="Student") for i in range(1, count + 1)]

def create_sample_attendance(teacher_school_number: str, lesson_name: str = "Test Lesson") -> Attendance:
    """Test için örnek bir Attendance nesnesi oluşturur."""
    return Attendance(
        attendance_id=uuid.uuid4(),
        teacher_school_number=teacher_school_number,
        lesson_name=lesson_name,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        security_option=1
    )

# ===== Test Senaryoları =====

@pytest.mark.asyncio
async def test_add_and_get_users(db_pool: asyncpg.Pool):
    """Senaryo: Kullanıcıları ekler ve geri alır."""
    client = AsyncPostgresClient(pool=db_pool)
    teacher = create_sample_teacher()
    students = create_sample_students(3)
    
    await client.add_users([teacher] + students)
    
    retrieved_teacher = await client.get_users([teacher.user_school_number])
    assert len(retrieved_teacher) == 1
    assert retrieved_teacher[0].user_school_number == teacher.user_school_number

    student_numbers = [s.user_school_number for s in students]
    retrieved_students = await client.get_users(student_numbers)
    assert len(retrieved_students) == 3

@pytest.mark.asyncio
async def test_add_and_get_attendance_records(db_pool: asyncpg.Pool):
    """
    Senaryo: Önceden var olan kullanıcılar için yoklama kayıtları ekler.
    Beklenti: Kullanıcılar zaten var olduğu için kayıtlar başarıyla eklenir.
    """
    client = AsyncPostgresClient(pool=db_pool)
    teacher = create_sample_teacher()
    students = create_sample_students(2)
    await client.add_users([teacher] + students)
    
    attendance_session = create_sample_attendance(teacher.user_school_number)
    await client.add_attendances([attendance_session])

    records_to_add = [
        AttendanceRecord(
            attendance_id=attendance_session.attendance_id,
            student_number=students[0].user_school_number,
            is_attended=True,
            attendance_time=datetime.now(timezone.utc)
        ),
        AttendanceRecord(
            attendance_id=attendance_session.attendance_id,
            student_number=students[1].user_school_number,
            is_attended=False,
            fail_reason="Absent"
        )
    ]
    
    await client.add_attendance_records(records_to_add)

    retrieved_records = await client.get_attendance_records(attendance_session.attendance_id)
    assert len(retrieved_records) == 2


@pytest.mark.asyncio
async def test_accept_historical_record(db_pool: asyncpg.Pool):
    """Senaryo: Geçmiş bir yoklama kaydını 'başarılı' olarak günceller."""
    client = AsyncPostgresClient(pool=db_pool)
    teacher, student = create_sample_teacher(), create_sample_students(1)[0]
    await client.add_users([teacher, student])
    attendance_session = create_sample_attendance(teacher.user_school_number)
    await client.add_attendances([attendance_session])
    
    initial_record = AttendanceRecord(
        attendance_id=attendance_session.attendance_id, 
        student_number=student.user_school_number, 
        is_attended=False,
        fail_reason="Initial fail"
    )
    await client.add_attendance_records([initial_record])

    await client.accept_historical_attendance_record(attendance_session.attendance_id, student.user_school_number)

    updated_records = await client.get_attendance_records(attendance_session.attendance_id)
    assert len(updated_records) == 1
    assert updated_records[0].is_attended is True
    assert updated_records[0].attendance_time is not None
    assert updated_records[0].fail_reason is None

@pytest.mark.asyncio
async def test_fail_historical_record(db_pool: asyncpg.Pool):
    """Senaryo: Geçmiş bir yoklama kaydını 'başarısız' olarak günceller."""
    client = AsyncPostgresClient(pool=db_pool)
    teacher, student = create_sample_teacher(), create_sample_students(1)[0]
    await client.add_users([teacher, student])
    attendance_session = create_sample_attendance(teacher.user_school_number)
    await client.add_attendances([attendance_session])
    
    initial_record = AttendanceRecord(
        attendance_id=attendance_session.attendance_id, 
        student_number=student.user_school_number, 
        is_attended=True,
        attendance_time=datetime.now(timezone.utc)
    )
    await client.add_attendance_records([initial_record])
    
    fail_reason = "Manual override by teacher"
    await client.fail_historical_attendance_record(attendance_session.attendance_id, student.user_school_number, reason=fail_reason)

    updated_records = await client.get_attendance_records(attendance_session.attendance_id)
    assert len(updated_records) == 1
    assert updated_records[0].is_attended is False
    assert updated_records[0].attendance_time is None
    assert updated_records[0].fail_reason == fail_reason

@pytest.mark.asyncio
async def test_soft_delete_attendance(db_pool: asyncpg.Pool):
    """Senaryo: Bir yoklamayı soft-delete eder ve artık get metoduyla gelmediğini doğrular."""
    client = AsyncPostgresClient(pool=db_pool)
    teacher = create_sample_teacher()
    await client.add_users([teacher])
    attendance_session = create_sample_attendance(teacher.user_school_number)
    await client.add_attendances([attendance_session])
    
    status_msg = await client.delete_attendance(attendance_id=attendance_session.attendance_id, reason="Test deletion")
    assert status_msg == "UPDATE 1"
    
    retrieved_attendances = await client.get_attendances(teacher.user_school_number)
    assert len(retrieved_attendances) == 0

@pytest.mark.asyncio
async def test_soft_delete_attendance_record(db_pool: asyncpg.Pool):
    """Senaryo: Bir yoklama kaydını soft-delete eder ve artık get metoduyla gelmediğini doğrular."""
    client = AsyncPostgresClient(pool=db_pool)
    teacher, student = create_sample_teacher(), create_sample_students(1)[0]
    await client.add_users([teacher, student])
    attendance_session = create_sample_attendance(teacher.user_school_number)
    await client.add_attendances([attendance_session])
    
    record = AttendanceRecord(attendance_id=attendance_session.attendance_id, student_number=student.user_school_number)
    await client.add_attendance_records([record])

    status_msg = await client.delete_attendance_record(
        attendance_id=record.attendance_id, 
        student_number=record.student_number, 
        reason="Student left early"
    )
    assert status_msg == "UPDATE 1"

    retrieved_records = await client.get_attendance_records(attendance_session.attendance_id)
    assert len(retrieved_records) == 0
