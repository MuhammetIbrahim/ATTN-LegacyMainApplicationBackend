import httpx
import uuid
from typing import Dict

# Gerekli ayarları ve modelleri import edelim
from ..config.config import settings
from ..db.redis_client import RedisClient
from ..models.db_models import User

class VerificationError(Exception):
    """Yüz tanıma işlemi sırasında oluşan hatalar için özel exception."""
    pass


async def submit_face_verification_job(
    student: User,
    attendance_id: uuid.UUID,
    normal_image_bytes: bytes,
    reference_image_bytes: bytes,
    redis_client: RedisClient
) -> str:
    """
    Yüz tanıma işini, geri çağrı (webhook) URL'i ile birlikte mikroservise gönderir.

    Bu fonksiyon artık bir 'job_id' beklemez. Bunun yerine, mikroservisin işi
    bitirdiğinde sonucu göndereceği eşsiz bir URL oluşturur ve bu URL'i mikroservise iletir.
    """
    # 1. Bu doğrulama işlemi için eşsiz ve tahmin edilemez bir ID oluştur
    verification_id = str(uuid.uuid4())

    # 2. Mikroservisin geri arayacağı tam webhook URL'ini oluştur.
    #    Bu URL, bizim Adım 1'de oluşturduğumuz endpoint'i işaret eder.
    #    MAIN_APP_BASE_URL .env dosyanızda tanımlı olmalı (örn: https://api.sizin-domaininiz.com)
    webhook_url = f"{settings.MAIN_APP_BASE_URL}/api/v1/webhooks/verification-result/{verification_id}"

    # 3. Mikroservise gönderilecek veriyi hazırla.
    #    'data' kısmı, form verisi olarak gönderilir.
    data = {
        'webhook_url': webhook_url,
        'verification_id': verification_id,
        "student_school_number": student.user_school_number,
    }
    # 'files' kısmı ise resim dosyalarını içerir.
    files = {
        'picture': ('image.jpg', normal_image_bytes, 'image/jpeg'),
        'intended_picture': ('reference_image.jpeg', reference_image_bytes, 'image/jpeg')
    }

    # 4. Redis'e geçici eşleşmeyi kaydet.
    #    Webhook geldiğinde, hangi öğrenciye ait olduğunu bu eşleşme sayesinde bileceğiz.
    await redis_client.map_verification_to_user(
        verification_id=verification_id,
        user_school_number=student.user_school_number,
        attendance_id=str(attendance_id)
    )

    # 5. İsteği mikroservise gönder.
    #    Not: Mikroservisin URL'i .env dosyasında FACE_VERIFIER_MICROSERVICE_URL olarak tanımlı olmalı.
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Artık /submit-job değil, doğrudan asenkron çalışacak bir endpoint'e gönderiyoruz.
            # Bu endpoint'i bir sonraki adımda mikroserviste oluşturacağız.
            response = await client.post(
                f"{settings.FACE_VERIFIER_MICROSERVICE_URL}/verify-face-async",
                files=files,
                data=data # `data` parametresi form verisi gönderir
            )
            response.raise_for_status() # HTTP 4xx veya 5xx hatalarında exception fırlatır

            # Mikroservis artık anında bir "kabul edildi" mesajı dönecek.
            # Gerçek sonuç daha sonra webhook ile gelecek.
            return "SUBMITTED"

        except httpx.HTTPStatusError as e:
            # İstek başarısız olursa, Redis'teki eşleşmeyi temizlememiz gerekir ki çöp veri kalmasın.
            await redis_client.delete_verification_mapping(verification_id)
            raise VerificationError(f"Submit Job - Mikroservis hatası: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            await redis_client.delete_verification_mapping(verification_id)
            raise VerificationError(f"Submit Job - Beklenmedik bir hata: {str(e)}")


# --- ARTIK GEREKLİ DEĞİL ---
# Bu fonksiyonun yerini webhook mekanizması aldığı için tamamen siliyoruz.
# async def verify_face_get_result(job_id: str) -> Dict:
#     ...
