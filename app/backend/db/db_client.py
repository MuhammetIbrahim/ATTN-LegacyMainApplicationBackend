import logging
from typing import List, Optional
from uuid import UUID
import asyncpg
from datetime import datetime, timezone
from ..models.db_models import User, Attendance, AttendanceRecord

logger = logging.getLogger(__name__)

class AsyncPostgresClient:
    """
    Tüm veritabanı operasyonlarını yöneten PostgreSQL istemcisi.
    """
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def add_users(self, users: List[User]):
        """Yeni kullanıcıları Users tablosuna ekler. Çakışma durumunda bir şey yapmaz."""
        if not users:
            return
        query = """
            INSERT INTO Users (user_school_number, user_full_name, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_school_number) DO NOTHING;
        """
        user_data = [(u.user_school_number, u.user_full_name, u.role) for u in users]
        async with self._pool.acquire() as connection:
            await connection.executemany(query, user_data)

    async def get_users(self, user_school_numbers: List[str]) -> List[User]:
        """Verilen okul numaralarına göre kullanıcı listesi döndürür."""
        if not user_school_numbers:
            return []
        query = "SELECT * FROM Users WHERE user_school_number = ANY($1);"
        async with self._pool.acquire() as connection:
            records = await connection.fetch(query, user_school_numbers)
            return [User(**record) for record in records]

    async def add_attendances(self, attendances: List[Attendance]):
        """Yeni yoklama oturumlarını Attendances tablosuna ekler."""
        if not attendances:
            return
        query = """
            INSERT INTO Attendances (attendance_id, teacher_school_number, lesson_name, ip_address, start_time, end_time, security_option)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (attendance_id) DO NOTHING;
        """
        attendance_data = [(
            att.attendance_id, att.teacher_school_number, att.lesson_name,
            att.ip_address, att.start_time, att.end_time, att.security_option
        ) for att in attendances]
        async with self._pool.acquire() as connection:
            await connection.executemany(query, attendance_data)

    async def get_attendances(self, teacher_school_number: str) -> List[Attendance]:
        """Bir öğretmenin silinmemiş tüm geçmiş yoklamalarını getirir."""
        query = "SELECT * FROM Attendances WHERE teacher_school_number = $1 AND is_deleted = FALSE;"
        async with self._pool.acquire() as connection:
            records = await connection.fetch(query, teacher_school_number)
            return [Attendance(**record) for record in records]

    async def get_attendance_by_id(self, attendance_id: UUID) -> Optional[Attendance]:
        """Tek bir yoklamayı ID ile getirir."""
        query = "SELECT * FROM Attendances WHERE attendance_id = $1 AND is_deleted = FALSE;"
        async with self._pool.acquire() as connection:
            record = await connection.fetchrow(query, attendance_id)
            return Attendance(**record) if record else None

    # --- REFACTORED METHOD ---
    async def add_attendance_records(self, records: List[AttendanceRecord]):
        """
        Öğrenci yoklama kayıtlarını ekler/günceller.
        Bu metod artık sadece db_models.AttendanceRecord kabul eder.
        Kullanıcı oluşturma sorumluluğu bu katmandan kaldırılmıştır ve cron job'a taşınmıştır.
        """
        if not records:
            return

        query = """
            INSERT INTO AttendanceRecords (attendance_id, student_number, is_attended, attendance_time, fail_reason)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (attendance_id, student_number) DO UPDATE SET
                is_attended = EXCLUDED.is_attended,
                attendance_time = EXCLUDED.attendance_time,
                fail_reason = EXCLUDED.fail_reason,
                is_deleted = FALSE, 
                deletion_reason = NULL,
                deletion_time = NULL;
        """
        record_data = [(
            rec.attendance_id, rec.student_number, rec.is_attended,
            rec.attendance_time, rec.fail_reason
        ) for rec in records]
        
        async with self._pool.acquire() as connection:
            await connection.executemany(query, record_data)

    async def get_attendance_records(self, attendance_id: UUID) -> List[AttendanceRecord]:
        """Bir yoklamanın tüm öğrenci kayıtlarını getirir."""
        query = "SELECT * FROM AttendanceRecords WHERE attendance_id = $1 AND is_deleted = FALSE;"
        async with self._pool.acquire() as connection:
            records = await connection.fetch(query, attendance_id)
            return [AttendanceRecord(**record) for record in records]
            
    async def accept_historical_attendance_record(self, attendance_id: UUID, student_number: str):
        """Geçmiş bir yoklama kaydını 'başarılı' olarak günceller."""
        query = """
            UPDATE AttendanceRecords
            SET is_attended = TRUE,
                attendance_time = $3,
                fail_reason = NULL,
                is_deleted = FALSE,
                deletion_reason = NULL,
                deletion_time = NULL
            WHERE attendance_id = $1 AND student_number = $2;
        """
        async with self._pool.acquire() as connection:
            return await connection.execute(query, attendance_id, student_number, datetime.now(timezone.utc))

    async def fail_historical_attendance_record(self, attendance_id: UUID, student_number: str, reason: str):
        """Geçmiş bir yoklama kaydını 'başarısız' olarak günceller."""
        query = """
            UPDATE AttendanceRecords
            SET is_attended = FALSE,
                attendance_time = NULL,
                fail_reason = $3,
                is_deleted = FALSE,
                deletion_reason = NULL,
                deletion_time = NULL
            WHERE attendance_id = $1 AND student_number = $2;
        """
        async with self._pool.acquire() as connection:
            return await connection.execute(query, attendance_id, student_number, reason)

    async def delete_attendance(self, attendance_id: UUID, reason: str):
        """Bir yoklamayı 'yumuşak silme' ile siler."""
        query = """
            UPDATE Attendances
            SET is_deleted = TRUE, deletion_reason = $2, deletion_time = $3
            WHERE attendance_id = $1;
        """
        async with self._pool.acquire() as connection:
            return await connection.execute(query, attendance_id, reason, datetime.now(timezone.utc))

    async def delete_attendance_record(self, attendance_id: UUID, student_number: str, reason: str):
        """Tek bir öğrenci kaydını 'yumuşak silme' ile siler."""
        query = """
            UPDATE AttendanceRecords
            SET is_deleted = TRUE, deletion_reason = $3, deletion_time = $4
            WHERE attendance_id = $1 AND student_number = $2;
        """
        async with self._pool.acquire() as connection:
            return await connection.execute(query, attendance_id, student_number, reason, datetime.now(timezone.utc))
