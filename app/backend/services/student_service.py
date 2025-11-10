import logging
import base64
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
import httpx

# --- Gerekli tüm istemciler ve modeller ---
from ..db.redis_client import RedisClient
from ..db.db_client import AsyncPostgresClient
from ..models.db_models import User
from ..models.redis_models import AttendanceRedis, AttendanceRecordRedis
# --- DEĞİŞİKLİK: Yeni face_verifier fonksiyonunu import ediyoruz ---
from ..tools.face_verifier import submit_face_verification_job, VerificationError
from ..tools.wifi_verifier import verify_wifi
from ..modules.aksis import AksisClient

logger = logging.getLogger(__name__)

class ServiceError(Exception):
    """Servis katmanı için genel hata sınıfı."""
    pass

class StudentService:
    """
    Öğrenciyle ilgili tüm iş mantığını yürüten servis katmanı.
    """
    def __init__(self, redis_client: RedisClient, db_client: AsyncPostgresClient):
        self.redis_client = redis_client
        self.db_client = db_client

    async def find_active_sessions_by_name(self, lesson_name: str, teacher_name: str) -> List[AttendanceRedis]:
        """
        Bir ders adı ve öğretmen adına göre tüm aktif yoklama oturumlarını Redis'ten bulur.
        Bu metod artık süresi dolmuş oturumları filtreler.
        """
        logger.info(f"Aktif ders aranıyor: Ders='{lesson_name}', Öğretmen='{teacher_name}'")
        try:
            sessions = await self.redis_client.get_attendance_sessions_by_name(lesson_name, teacher_name)
            
            # Sadece süresi dolmamış (aktif) oturumları döndür.
            now = datetime.now(timezone.utc)
            active_sessions = [session for session in sessions if session.end_time > now]
            
            return active_sessions
        except Exception as e:
            logger.error("Aktif dersler aranırken Redis hatası oluştu.", exc_info=True)
            raise ServiceError("Dersler aranırken bir sunucu hatası oluştu.") from e

    async def attend_to_attendance(self,
                                         student: User,
                                         attendance_id: UUID,
                                         student_ip: Optional[str] = None,
                                         normal_image_bytes: Optional[bytes] = None
                                         ) -> AttendanceRecordRedis:
        """Bir öğrencinin belirli bir ID'ye sahip derse katılımını işler."""
        logger.info(f"Öğrenci '{student.user_school_number}' yoklamaya ({attendance_id}) katılma girişiminde bulunuyor.")
        
        active_attendance = await self.redis_client.get_attendance_session(attendance_id)
        if not active_attendance:
            logger.warning(f"Öğrenci '{student.user_school_number}' var olmayan bir derse ({attendance_id}) katılmaya çalıştı.")
            raise ServiceError("This attendance session does not exist.")

        if active_attendance.end_time <= datetime.now(timezone.utc):
            logger.warning(f"Öğrenci '{student.user_school_number}' süresi dolmuş bir derse ({attendance_id}) katılmaya çalıştı.")
            raise ServiceError("This attendance session has already ended.")

        existing_record = await self.redis_client.get_attendance_record_by_id(attendance_id, student.user_school_number)
        if existing_record:
            if existing_record.is_attended:
                raise ServiceError("You have already successfully joined this session.")
            if existing_record.fail_reason == "FACE_RECOGNITION_PENDING":
                raise ServiceError("Your attendance is already pending verification. Please wait.")

        fail_reason: Optional[str] = None
        security_option = active_attendance.security_option
        logger.info(f"Yoklama ({attendance_id}) güvenlik seviyesi: {security_option}")

        # --- Güvenlik Kontrolleri ---
        try:
            if security_option >= 2:
                logger.info(f"WiFi check - Student IP: '{student_ip}', Session IP: '{active_attendance.ip_address}', Match: {student_ip == active_attendance.ip_address if student_ip and active_attendance.ip_address else False}")
                if not student_ip or not verify_wifi(active_attendance, student_ip):
                    logger.warning(f"WiFi verification FAILED - Student IP: '{student_ip}', Session IP: '{active_attendance.ip_address}'")
                    fail_reason = "WIFI_FAILED"
            
            if security_option == 3 and fail_reason is None:
                if not normal_image_bytes:
                    fail_reason = "FACE_VERIFICATION_REQUIRED_BUT_IMAGE_MISSING"
                else:
                    user_session = await self.redis_client.get_user_session(student.user_school_number)
                    if not user_session or not user_session.image_url:
                        fail_reason = "REFERENCE_IMAGE_NOT_FOUND"
                    else:
                        try:
                            # Isolated HTTP client for image download
                            async with httpx.AsyncClient(
                                timeout=30.0,
                                cookies=httpx.Cookies()
                            ) as http_client:
                                aksis_client = AksisClient(school_number="", password="", http_client=http_client)
                                ref_image_b64 = await aksis_client.get_profile_image_base64(user_session.image_url)
                                reference_image_bytes = base64.b64decode(ref_image_b64)
                                
                                # ================================================================= #
                                # --- REFACTORING BURADA BAŞLIYOR ---
                                # ================================================================= #
                                # Eski polling (sorgulama) mantığı yerine yeni webhook sistemini kullanıyoruz.
                                # Artık bir 'job_id' almıyoruz ve kullanıcıyı bir sıraya eklemiyoruz.

                                await submit_face_verification_job(
                                    student=student,
                                    attendance_id=active_attendance.attendance_id,
                                    normal_image_bytes=normal_image_bytes,
                                    reference_image_bytes=reference_image_bytes,
                                    # Bu servis instance'ının sahip olduğu redis_client'ı doğrudan iletiyoruz.
                                    redis_client=self.redis_client
                                )
                                # Durum hala "beklemede", ama artık arka planda bir cron job tarafından
                                # sorgulanmayacak. Sonuç doğrudan webhook ile gelecek.
                                fail_reason = "FACE_RECOGNITION_PENDING"
                                # ================================================================= #
                                # --- REFACTORING BURADA BİTİYOR ---
                                # ================================================================= #

                        except VerificationError as e:
                            fail_reason = "FACE_VERIFICATION_SUBMISSION_FAILED"
                            logger.error(f"Yüz tanıma işi gönderilirken hata oluştu: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Katılım işlemi sırasında beklenmedik bir hata oluştu: {e}", exc_info=True)
            raise ServiceError("An unexpected error occurred during the attendance process.")

        # --- Sonuç Kaydını Oluşturma ---
        final_is_attended = fail_reason is None
        new_record = AttendanceRecordRedis(
            attendance_id=active_attendance.attendance_id,
            student_number=student.user_school_number,
            student_full_name=student.user_full_name,
            is_attended=final_is_attended,
            attendance_time=datetime.now(timezone.utc) if final_is_attended else None,
            fail_reason=fail_reason
        )
        
        await self.redis_client.add_attendance_record(new_record)
        return new_record

    async def get_my_attendance_status(self, attendance_id: UUID, student: User) -> Optional[AttendanceRecordRedis]:
        """Bir öğrencinin belirli bir dersteki yoklama durumunu getirir."""
        logger.info(f"Öğrenci '{student.user_school_number}' yoklama ({attendance_id}) durumunu sorguluyor.")
        try:
            # --- YENİ EKLENEN KONTROL ---
            # Önce yoklama oturumunun kendisini alarak hala aktif olup olmadığını kontrol et.
            attendance_session = await self.redis_client.get_attendance_session(attendance_id)
            if not attendance_session:
                # Oturum hiç yoksa, öğrencinin kaydı da olamaz. Hata vermeye gerek yok, None dönmek yeterli.
                return None
            
            # Oturumun süresi dolmuşsa, artık durum sorgulamaya izin verme.
            if attendance_session.end_time <= datetime.now(timezone.utc):
                logger.warning(f"Öğrenci '{student.user_school_number}' süresi dolmuş bir dersin ({attendance_id}) durumunu sorguladı.")
                raise ServiceError("This attendance session has already ended.")
            # --- KONTROL SONU ---

            # Oturum aktifse, öğrencinin kendi kaydını getir.
            return await self.redis_client.get_attendance_record_by_id(
                attendance_id=attendance_id, 
                student_number=student.user_school_number
            )
        except Exception as e:
            # ServiceError'ı tekrar raise etme, çünkü onu zaten handle ediyoruz.
            if isinstance(e, ServiceError):
                raise e
            logger.error("Öğrenci yoklama durumu sorgulanırken Redis hatası oluştu.", exc_info=True)
            raise ServiceError("An error occurred while querying your attendance status.") from e
