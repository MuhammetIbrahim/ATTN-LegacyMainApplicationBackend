import hmac
import hashlib
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from pydantic import BaseModel, ValidationError
from uuid import UUID


# Bağımlılıkları ve modelleri doğru yerden import edelim
from ..db.redis_client import RedisClient
from ..config.config import settings
from .dependencies import get_redis_pool
import redis.asyncio as redis
from .utilities.limiter import limiter

# .env dosyanıza ekleyeceğiniz gizli anahtar
WEBHOOK_SECRET_KEY = settings.WEBHOOK_SECRET_KEY.encode('utf-8')

router = APIRouter(prefix="/webhooks",tags=["Microservice Webhooks"])

class VerificationResultPayload(BaseModel):
    verification_passed: bool
    reason: str

def get_webhook_redis_client(redis_pool: redis.ConnectionPool = Depends(get_redis_pool)) -> RedisClient:
    return RedisClient(pool=redis_pool)


@router.post("/verification-result/{verification_id}")
@limiter.limit("200/minute")
async def update_attendance_from_webhook(
    verification_id: uuid.UUID,
    request: Request,
    x_webhook_signature: str = Header(..., description="HMAC-SHA256 imzası"),
    redis_client: RedisClient = Depends(get_webhook_redis_client)
):
    """
    Mikroservisten gelen sonucu alır, doğrular ve yoklama kaydını günceller.
    """
    # 1. GÜVENLİK: İmzanın doğruluğunu kontrol et
    raw_body = await request.body()
    expected_signature = hmac.new(key=WEBHOOK_SECRET_KEY, msg=raw_body, digestmod=hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, x_webhook_signature):
        raise HTTPException(status_code=403, detail="Geçersiz webhook imzası.")

    # 2. PAYLOAD'I AYRIŞTIR
    try:
        data = json.loads(raw_body)
        payload = VerificationResultPayload(**data.get('overall_result', {}))
    except (json.JSONDecodeError, ValidationError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"Hatalı payload formatı: {e}")

    # 3. MANTIK: MEVCUT REDIS METODLARINI KULLAN
    # Bu doğrulama ID'sine karşılık gelen öğrenci ve yoklama bilgilerini al
    verification_data = await redis_client.get_user_and_attendance_for_verification(str(verification_id))
    if not verification_data:
        return {"status": "İşlem bulunamadı veya zaten işlenmiş."}

    user_school_number = verification_data["user_school_number"]
    attendance_id = UUID(verification_data["attendance_id"])

    # Mevcut yoklama kaydını getir
    attendance_record = await redis_client.get_attendance_record_by_id(attendance_id, user_school_number)
    if not attendance_record:
        # Bu bir "edge case" ama yine de handle edelim
        await redis_client.delete_verification_mapping(str(verification_id))
        raise HTTPException(status_code=404, detail="Yoklama kaydı bulunamadı.")

    # Kaydı güncelle
    if payload.verification_passed:
        attendance_record.is_attended = True
        attendance_record.attendance_time = datetime.now(timezone.utc)
        attendance_record.fail_reason = None
    else:
        attendance_record.is_attended = False
        attendance_record.fail_reason = f"FACE_VERIFICATION_FAILED: {payload.reason}"

    # Güncellenmiş kaydı Redis'e geri yaz
    await redis_client.update_attendance_record(attendance_record)

    # 4. TEMİZLİK: Geçici eşleşmeyi sil
    await redis_client.delete_verification_mapping(str(verification_id))

    return {"status": "success"}