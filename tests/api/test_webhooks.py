import pytest
import pytest_asyncio
import uuid
import hmac
import hashlib
import json
from httpx import AsyncClient, ASGITransport
from typing import Dict, AsyncIterator
from datetime import datetime, timezone

# Gerekli modelleri, istemciyi ve uygulamayı doğrudan ana koddan import et
from app.backend.main import app
from app.backend.config.config import settings
from app.backend.db.redis_client import RedisClient
from app.backend.models.redis_models import AttendanceRecordRedis
from app.backend.api.webhooks import get_webhook_redis_client # Override edilecek dependency
import redis.asyncio as redis

# ----- Test için kullanılacak sabitler -----
WEBHOOK_SECRET_KEY = settings.WEBHOOK_SECRET_KEY.encode('utf-8')
TEST_REDIS_URL = "redis://localhost:6379/0"

# ----- Fikstürler (Bu dosyaya özel test altyapısı) -----

@pytest.fixture(scope="module")
def anyio_backend():
    """Testlerin asyncio modunda çalışmasını sağlar."""
    return 'asyncio'

@pytest_asyncio.fixture(scope="function")
async def redis_pool():
    """Bu test dosyasındaki her test için temiz bir Redis bağlantı havuzu oluşturur."""
    pool = redis.ConnectionPool.from_url(TEST_REDIS_URL, decode_responses=True)
    yield pool
    # Test sonrası temizlik
    await pool.disconnect()

@pytest_asyncio.fixture(scope="function")
async def http_client(redis_pool) -> AsyncIterator[AsyncClient]:
    """
    Her test için yeni bir HTTP istemcisi oluşturur ve Redis bağımlılığını override eder.
    """
    def override_get_redis_client() -> RedisClient:
        return RedisClient(pool=redis_pool)

    app.dependency_overrides[get_webhook_redis_client] = override_get_redis_client

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ----- Yardımcı Fonksiyonlar -----

# Artık bu yardımcı fonksiyona gerek yok, çünkü imzayı testin içinde oluşturacağız.
# def create_signature(payload: Dict) -> str: ...

def create_sample_attendance_record_redis(
    attendance_id: uuid.UUID,
    student_number: str = "S001"
) -> AttendanceRecordRedis:
    """Testler için standart bir yoklama kaydı oluşturur."""
    return AttendanceRecordRedis(
        attendance_id=attendance_id,
        student_number=student_number,
        student_full_name="Test Student",
        is_attended=False,
        attendance_time=None,
        fail_reason=None
    )

# ----- Test Senaryoları -----

@pytest.mark.asyncio
async def test_webhook_success_verification_passed(http_client: AsyncClient, redis_pool):
    """
    Senaryo: Geçerli ve başarılı bir webhook isteği geldiğinde yoklama kaydı güncellenir.
    """
    redis_client = RedisClient(pool=redis_pool)
    verification_id = uuid.uuid4()
    student_number = "S-SUCCESS"
    attendance_id = uuid.uuid4()

    record = create_sample_attendance_record_redis(attendance_id, student_number)
    await redis_client.add_attendance_record(record)
    await redis_client.map_verification_to_user(str(verification_id), student_number, str(attendance_id))

    # --- DÜZELTME: İsteği ve imzayı manuel olarak oluşturuyoruz ---
    payload = {"overall_result": {"verification_passed": True, "reason": "Faces match."}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = hmac.new(key=WEBHOOK_SECRET_KEY, msg=payload_bytes, digestmod=hashlib.sha256).hexdigest()

    response = await http_client.post(
        f"/api/v1/webhooks/verification-result/{verification_id}",
        content=payload_bytes,
        headers={
            "X-Webhook-Signature": signature,
            "Content-Type": "application/json"
        }
    )
    # --- DÜZELTME SONU ---

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    updated_record = await redis_client.get_attendance_record_by_id(attendance_id, student_number)
    assert updated_record.is_attended is True
    assert await redis_client.get_user_and_attendance_for_verification(str(verification_id)) is None

@pytest.mark.asyncio
async def test_webhook_success_verification_failed(http_client: AsyncClient, redis_pool):
    """
    Senaryo: Geçerli ama başarısız bir webhook isteği geldiğinde yoklama kaydı güncellenir.
    """
    redis_client = RedisClient(pool=redis_pool)
    verification_id = uuid.uuid4()
    student_number = "S-FAILURE"
    attendance_id = uuid.uuid4()

    record = create_sample_attendance_record_redis(attendance_id, student_number)
    await redis_client.add_attendance_record(record)
    await redis_client.map_verification_to_user(str(verification_id), student_number, str(attendance_id))

    # --- DÜZELTME: İsteği ve imzayı manuel olarak oluşturuyoruz ---
    payload = {"overall_result": {"verification_passed": False, "reason": "Faces do not match."}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = hmac.new(key=WEBHOOK_SECRET_KEY, msg=payload_bytes, digestmod=hashlib.sha256).hexdigest()

    response = await http_client.post(
        f"/api/v1/webhooks/verification-result/{verification_id}",
        content=payload_bytes,
        headers={
            "X-Webhook-Signature": signature,
            "Content-Type": "application/json"
        }
    )
    # --- DÜZELTME SONU ---

    assert response.status_code == 200
    updated_record = await redis_client.get_attendance_record_by_id(attendance_id, student_number)
    assert updated_record.is_attended is False
    assert "FACE_VERIFICATION_FAILED" in updated_record.fail_reason
    assert await redis_client.get_user_and_attendance_for_verification(str(verification_id)) is None

@pytest.mark.asyncio
async def test_webhook_security_fail_invalid_signature(http_client: AsyncClient, redis_pool):
    """
    Senaryo: Geçersiz bir imza ile gelen istek reddedilir (403 Forbidden).
    """
    redis_client = RedisClient(pool=redis_pool)
    verification_id = uuid.uuid4()
    student_number = "S-SECURITY"
    attendance_id = uuid.uuid4()

    record = create_sample_attendance_record_redis(attendance_id, student_number)
    await redis_client.add_attendance_record(record)
    await redis_client.map_verification_to_user(str(verification_id), student_number, str(attendance_id))

    payload = {"overall_result": {"verification_passed": True, "reason": "Faces match."}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    # İmza hala doğru payload'a göre oluşturuluyor ama biz yanlış bir imza göndereceğiz
    invalid_signature = "this-is-an-intentionally-wrong-signature"

    response = await http_client.post(
        f"/api/v1/webhooks/verification-result/{verification_id}",
        content=payload_bytes,
        headers={
            "X-Webhook-Signature": invalid_signature,
            "Content-Type": "application/json"
        }
    )

    assert response.status_code == 403
    original_record = await redis_client.get_attendance_record_by_id(attendance_id, student_number)
    assert original_record.is_attended is False

@pytest.mark.asyncio
async def test_webhook_data_fail_invalid_payload(http_client: AsyncClient):
    """
    Senaryo: Geçerli imza ama hatalı payload ile gelen istek reddedilir (422 Unprocessable Entity).
    """
    verification_id = uuid.uuid4()
    # Hatalı payload
    payload = {"overall_result": {"reason": "Some reason."}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    signature = hmac.new(key=WEBHOOK_SECRET_KEY, msg=payload_bytes, digestmod=hashlib.sha256).hexdigest()

    response = await http_client.post(
        f"/api/v1/webhooks/verification-result/{verification_id}",
        content=payload_bytes,
        headers={
            "X-Webhook-Signature": signature,
            "Content-Type": "application/json"
        }
    )

    assert response.status_code == 422
