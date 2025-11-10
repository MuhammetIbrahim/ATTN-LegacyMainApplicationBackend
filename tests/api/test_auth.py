import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os

# Test edilecek ana FastAPI uygulamasını ve diğer gerekli modülleri import edelim
from app.backend.main import app
from app.backend.modules.aksis import AksisAuthError, AksisSessionError
from app.backend.config.config import settings

# --- Test Verileri (Yeni demo kullanıcı formatına göre güncellendi) ---
DEMO_TEACHER_PAYLOAD = {"username": "demo_teacher_1", "password": "password"}
DEMO_STUDENT_PAYLOAD = {"username": "demo_student_1", "password": "password"}
# Aksis testleri için .env dosyasından değerleri al, yoksa atla
REAL_STUDENT_PAYLOAD = {"username": settings.AKSIS_STUDENT_USERNAME, "password": settings.AKSIS_STUDENT_PASSWORD}
INCORRECT_PAYLOAD = {"username": "wrong_user", "password": "wrong_password"}

# --- Test Senaryoları ---

def test_demo_teacher_login_success():
    """
    Senaryo: Demo öğretmen kullanıcısı ile başarılı giriş.
    Beklenti: 200 OK status kodu ve doğru öğretmen verileri.
    """
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json=DEMO_TEACHER_PAYLOAD)
    
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "access_token" in data["token"]
    assert data["user"]["role"] == "Teacher"
    assert data["user"]["user_school_number"] == "demo_teacher_1"
    assert data["user"]["user_full_name"] == "Demo Teacher 1" 
    assert data["schedule"] is None

def test_demo_student_login_success():
    """
    Senaryo: Demo öğrenci kullanıcısı ile başarılı giriş.
    Beklenti: 200 OK status kodu, doğru öğrenci verileri ve ders programı.
    """
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json=DEMO_STUDENT_PAYLOAD)
    
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["user"]["role"] == "Student"
    assert data["user"]["user_school_number"] == "demo_student_1"
    assert data["user"]["user_full_name"] == "Demo Student 1"
    assert data["schedule"] is not None
    assert data["schedule"][0]["lesson_name"] == "Yazılım Mühendisliği"

@pytest.mark.skipif(not all([settings.AKSIS_STUDENT_USERNAME, settings.AKSIS_STUDENT_PASSWORD]), reason="Aksis test credentials not set in .env")
@patch("app.backend.api.auth.AksisClient", autospec=True)
def test_real_student_login_success(mock_aksis_client_class: MagicMock):
    """
    Senaryo: Gerçek öğrenci bilgileriyle başarılı giriş (Aksis mock'lanarak).
    Beklenti: 200 OK ve Aksis'ten dönen verilerle oluşturulmuş yanıt.
    """
    # Asenkron metodların senkron testlerde doğru değer döndürmesi için ayarlama
    async def mock_login(): return {"role": "Student"}
    async def mock_get_obs_profile(): 
        return {
            "school_number": settings.AKSIS_STUDENT_USERNAME,
            "full_name": "Gerçek Test Öğrencisi",
            "image_url": "http://example.com/real.jpg"
        }
    async def mock_get_daily_schedule(*args, **kwargs): return [{"lesson_name": "Calculus", "time": "10:00"}]
    # Note: close_session method no longer exists - using singleton HTTP client

    mock_aksis_instance = mock_aksis_client_class.return_value
    mock_aksis_instance.login = mock_login
    mock_aksis_instance.get_obs_profile = mock_get_obs_profile
    mock_aksis_instance.get_daily_schedule = mock_get_daily_schedule
    # Note: No longer need to mock close_session

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json=REAL_STUDENT_PAYLOAD)
    
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["role"] == "Student"
    assert data["user"]["user_school_number"] == settings.AKSIS_STUDENT_USERNAME
    assert data["user"]["user_full_name"] == "Gerçek Test Öğrencisi"
    assert len(data["schedule"]) == 1

@patch("app.backend.api.auth.AksisClient.login", side_effect=AksisAuthError("Invalid credentials"))
def test_login_wrong_credentials_fail(mock_login):
    """
    Senaryo: Yanlış parola ile giriş denemesi.
    Beklenti: 401 Unauthorized hatası.
    """
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json=INCORRECT_PAYLOAD)
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."

def test_logout_success():
    """
    Senaryo: Başarılı bir giriş sonrası çıkış yapma.
    Beklenti: 204 No Content status kodu.
    """
    with TestClient(app) as client:
        # Önce giriş yap
        login_response = client.post("/api/v1/auth/login", json=DEMO_STUDENT_PAYLOAD)
        assert login_response.status_code == 200
        token = login_response.json()["token"]["access_token"]
        
        # Alınan token ile çıkış yap
        headers = {"Authorization": f"Bearer {token}"}
        logout_response = client.post("/api/v1/auth/logout", headers=headers)
        
        assert logout_response.status_code == 204

def test_logout_invalid_token_fail():
    """
    Senaryo: Geçersiz bir token ile çıkış yapma denemesi.
    Beklenti: 401 Unauthorized hatası.
    """
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer thisisafaketoken"}
        response = client.post("/api/v1/auth/logout", headers=headers)
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"

def test_access_after_logout_fails():
    """
    Senaryo: Başarılı bir çıkış sonrası aynı token ile tekrar erişim denemesi.
    Beklenti: 401 Unauthorized hatası (Redis kontrolü sayesinde).
    """
    with TestClient(app) as client:
        # 1. Giriş yap ve token al
        login_response = client.post("/api/v1/auth/login", json=DEMO_TEACHER_PAYLOAD)
        assert login_response.status_code == 200
        token = login_response.json()["token"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Çıkış yap (Redis oturumu silinir)
        logout_response = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_response.status_code == 204

        # 3. Aynı token ile tekrar istekte bulun
        # get_current_user bağımlılığı olan herhangi bir endpoint olabilir.
        # Logout en basiti.
        final_attempt_response = client.post("/api/v1/auth/logout", headers=headers)

        # 4. Erişimin engellendiğini doğrula
        assert final_attempt_response.status_code == 401
        assert final_attempt_response.json()["detail"] == "Could not validate credentials"

