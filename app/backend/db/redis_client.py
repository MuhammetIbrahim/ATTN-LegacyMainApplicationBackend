import logging
from typing import List, Optional, Dict
from uuid import UUID
import redis.asyncio as redis
import asyncio
from datetime import datetime, timezone

# --- Gerekli tüm modeller ---
from ..models.redis_models import UserSessionRedis, AttendanceRedis, AttendanceRecordRedis

logger = logging.getLogger(__name__)

class RedisClient:
    """
    Tüm cache ve oturum operasyonlarını yöneten Redis istemcisi.
    """
    
    def __init__(self, pool: redis.ConnectionPool):
        self._redis = redis.Redis(connection_pool=pool, decode_responses=True)

    # ===== User Session Management =====

    async def save_user_session(self, user: UserSessionRedis, ttl: int):
        """Kullanıcı oturumunu TTL ile Redis'e kaydeder."""
        key = f"users:{user.user_data.user_school_number}"
        await self._redis.set(key, user.model_dump_json(), ex=ttl)

    async def get_user_session(self, user_school_number: str) -> Optional[UserSessionRedis]:
        """Kullanıcı oturumunu Redis'ten alır."""
        key = f"users:{user_school_number}"
        user_json = await self._redis.get(key)
        return UserSessionRedis.model_validate_json(user_json) if user_json else None

    async def delete_user_session(self, user_school_number: str) -> int:
        """Kullanıcı oturumunu Redis'ten siler."""
        key = f"users:{user_school_number}"
        return await self._redis.delete(key)

    # ===== Full Attendance Session Management =====

    async def save_attendance_session(self, attendance: AttendanceRedis):
        """
        Tam yoklama oturumu nesnesini Redis'e kaydeder ve arama için indeksler oluşturur.
        """
        session_key = f"attendance_session:{attendance.attendance_id}"
        index_key_by_name = f"attendance_index:name:{attendance.lesson_name}:{attendance.teacher_full_name}"
        index_key_by_teacher = f"attendance_index:teacher:{attendance.teacher_school_number}"

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(session_key, attendance.model_dump_json())
            pipe.sadd(index_key_by_name, str(attendance.attendance_id))
            pipe.sadd(index_key_by_teacher, str(attendance.attendance_id))
            await pipe.execute()

    async def get_attendance_session(self, attendance_id: UUID) -> Optional[AttendanceRedis]:
        """Tam yoklama oturumu nesnesini ID ile alır."""
        key = f"attendance_session:{attendance_id}"
        session_json = await self._redis.get(key)
        return AttendanceRedis.model_validate_json(session_json) if session_json else None

    async def get_attendance_sessions_by_name(self, lesson_name: str, teacher_name: str) -> List[AttendanceRedis]:
        """Ders adı ve öğretmen adına göre aktif yoklama oturumlarını bulur."""
        index_key = f"attendance_index:name:{lesson_name}:{teacher_name}"
        attendance_ids = await self._redis.smembers(index_key)
        if not attendance_ids:
            return []
        
        # NOTE: Bu kısım da zaman kontrolü eklenerek daha da iyileştirilebilir.
        # Şimdilik sadece öğretmenin aktif ders kontrolüne odaklanıyoruz.
        tasks = [self.get_attendance_session(UUID(att_id)) for att_id in attendance_ids]
        sessions = await asyncio.gather(*tasks)
        return [session for session in sessions if session is not None]

    # --- REFACTORED METHOD WITH TIME CHECK ---
    async def get_attendance_session_of_teacher(self, teacher_school_number: str) -> Optional[AttendanceRedis]:
        """
        Bir öğretmenin aktif yoklama otorumunu bulur. Bir öğretmen sadece bir aktif oturuma sahip olabilir.
        Bu metod artık oturumun süresinin dolup dolmadığını da kontrol eder.
        """
        index_key = f"attendance_index:teacher:{teacher_school_number}"
        attendance_ids = await self._redis.smembers(index_key)
        if not attendance_ids:
            return None
        
        attendance_id = attendance_ids.pop()
        session = await self.get_attendance_session(UUID(attendance_id))
        
        # EKLENEN KONTROL: Oturum bulunduysa, süresinin geçip geçmediğini kontrol et.
        # Süresi dolmuşsa, "aktif değil" kabul et ve None döndür. Cron job onu daha sonra temizleyecektir.
        if session and session.end_time > datetime.now(timezone.utc):
            return session
        
        return None

    async def delete_attendance_session(self, attendance: AttendanceRedis):
        """Tam yoklama oturumu nesnesini ve ilgili indekslerini Redis'ten siler."""
        session_key = f"attendance_session:{attendance.attendance_id}"
        index_key_by_name = f"attendance_index:name:{attendance.lesson_name}:{attendance.teacher_full_name}"
        index_key_by_teacher = f"attendance_index:teacher:{attendance.teacher_school_number}"
        
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(session_key)
            pipe.srem(index_key_by_name, str(attendance.attendance_id))
            pipe.srem(index_key_by_teacher, str(attendance.attendance_id))
            await pipe.execute()
        
    # ===== Attendance Record Management (Öğrenci Kayıtları) =====

    async def add_attendance_record(self, record: AttendanceRecordRedis):
        """Öğrencinin yoklama kaydını kaydeder."""
        key = f"attendance_records:{record.attendance_id}:{record.student_number}"
        await self._redis.set(key, record.model_dump_json())

    async def get_attendance_records(self, attendance_id: UUID) -> List[AttendanceRecordRedis]:
        """Bir yoklamanın tüm öğrenci kayıtlarını getirir."""
        records = []
        async for key in self._redis.scan_iter(f"attendance_records:{attendance_id}:*"):
            record_json = await self._redis.get(key)
            if record_json:
                records.append(AttendanceRecordRedis.model_validate_json(record_json))
        return records
    
    async def get_attendance_record_by_id(self, attendance_id: UUID, student_number: str) -> Optional[AttendanceRecordRedis]:
        """Tek bir öğrenci kaydını getirir."""
        key = f"attendance_records:{attendance_id}:{student_number}"
        record_json = await self._redis.get(key)
        return AttendanceRecordRedis.model_validate_json(record_json) if record_json else None

    async def update_attendance_record(self, record: AttendanceRecordRedis):
        """Mevcut bir öğrenci kaydını günceller."""
        await self.add_attendance_record(record)
        
   
 # ===== Webhook Verification Mapping =====

    async def map_verification_to_user(self, verification_id: str, user_school_number: str, attendance_id: str):
        """
        Geçici olarak bir doğrulama ID'sini bir kullanıcıya ve yoklama ID'sine bağlar.
        Bu anahtarın ömrü kısa olmalı (örn: 5 dakika), işlenmeyen isteklerin birikmemesi için.
        """
        key = f"verification:{verification_id}"
        # Hem okul numarası hem de yoklama ID'sini tek bir string'de saklıyoruz.
        value = f"{user_school_number}:{attendance_id}"
        await self._redis.set(key, value, ex=300) # 300 saniye = 5 dakika

    async def get_user_and_attendance_for_verification(self, verification_id: str) -> Optional[Dict[str, str]]:
        """Bir doğrulama ID'sine karşılık gelen kullanıcıyı ve yoklama ID'sini getirir."""
        key = f"verification:{verification_id}"
        value = await self._redis.get(key)
        if not value:
            return None
        
        parts = value.split(':')
        if len(parts) != 2:
            return None # Hatalı format
        
        return {"user_school_number": parts[0], "attendance_id": parts[1]}

    async def delete_verification_mapping(self, verification_id: str):
        """İşlem tamamlandığında geçici eşleşmeyi siler."""
        key = f"verification:{verification_id}"
        await self._redis.delete(key)