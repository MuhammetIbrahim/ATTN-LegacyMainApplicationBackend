import pytest
import uuid
from unittest.mock import AsyncMock
from pathlib import Path

# Test edilecek refactor edilmiş fonksiyon ve exception
from app.backend.tools.face_verifier import submit_face_verification_job, VerificationError
from app.backend.config.config import settings
from app.backend.models.db_models import User

# --- Pytest İşaretleri ---
integration_test = pytest.mark.skipif(
    not settings.FACE_VERIFIER_MICROSERVICE_URL,
    reason="Face verifier testi için FACE_VERIFIER_MICROSERVICE_URL gereklidir."
)

# --- Fikstürler ---

@pytest.fixture(scope="session")
def real_image_bytes():
    """
    Test için GERÇEK imaj dosyalarını okur ve byte olarak döner.
    """
    try:
        image_path = Path(__file__).parent.parent / "test_images" / "image.jpg"
        reference_path = Path(__file__).parent.parent / "test_images" / "reference_image.jpeg"
        
        with open(image_path, "rb") as f:
            normal_image = f.read()
        with open(reference_path, "rb") as f:
            reference_image = f.read()
        
        return {"normal": normal_image, "reference": reference_image}
    except FileNotFoundError as e:
        pytest.fail(f"Test imajı bulunamadı: {e}. 'tests/test_images' klasörünü ve imajları kontrol edin.")

@pytest.fixture
def mock_student() -> User:
    """Testler için standart bir öğrenci nesnesi oluşturur."""
    return User(user_school_number="S12345", user_full_name="Test Öğrenci", role="Student")

@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """RedisClient'ın davranışlarını taklit eden bir mock nesnesi sağlar."""
    return AsyncMock()

# --- Refactor Edilmiş Entegrasyon Testleri ---

@integration_test
@pytest.mark.asyncio
async def test_submit_job_success(
    real_image_bytes,
    mock_student,
    mock_redis_client,
    httpx_mock  # httpx isteklerini taklit etmek için kullanılır
):
    """
    Senaryo: İşin mikroservise başarıyla gönderilmesini test eder.
    """
    # 1. Hazırlık: Mikroservisin başarılı (202 Accepted) döneceğini varsayalım
    microservice_url = f"{settings.FACE_VERIFIER_MICROSERVICE_URL}/verify-face-async"
    httpx_mock.add_response(method="POST", url=microservice_url, status_code=202, json={"status": "job accepted"})

    # 2. Çalıştırma
    attendance_id = uuid.uuid4()
    result = await submit_face_verification_job(
        student=mock_student,
        attendance_id=attendance_id,
        normal_image_bytes=real_image_bytes["normal"],
        reference_image_bytes=real_image_bytes["reference"],
        redis_client=mock_redis_client
    )

    # 3. Doğrulama
    assert result == "SUBMITTED"
    mock_redis_client.map_verification_to_user.assert_awaited_once()
    mock_redis_client.delete_verification_mapping.assert_not_awaited()


@integration_test
@pytest.mark.asyncio
async def test_submit_job_microservice_returns_error(
    real_image_bytes,
    mock_student,
    mock_redis_client,
    httpx_mock
):
    """
    Senaryo: Mikroservis bir hata (örn: 500) döndürdüğünde hata yönetimini test eder.
    """
    # 1. Hazırlık: Mikroservisin 500 Internal Server Error döneceğini varsayalım
    microservice_url = f"{settings.FACE_VERIFIER_MICROSERVICE_URL}/verify-face-async"
    httpx_mock.add_response(method="POST", url=microservice_url, status_code=500, text="Internal Server Error")

    # 2. Çalıştırma ve Hata Doğrulama
    attendance_id = uuid.uuid4()
    with pytest.raises(VerificationError, match="Mikroservis hatası: 500"):
        await submit_face_verification_job(
            student=mock_student,
            attendance_id=attendance_id,
            normal_image_bytes=real_image_bytes["normal"],
            reference_image_bytes=real_image_bytes["reference"],
            redis_client=mock_redis_client
        )

    # 3. Temizlik Doğrulama
    mock_redis_client.map_verification_to_user.assert_awaited_once()
    mock_redis_client.delete_verification_mapping.assert_awaited_once()
