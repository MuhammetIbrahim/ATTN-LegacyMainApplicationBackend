# tests/tools/test_wifi_verifier.py

import pytest
import httpx
import uuid
from datetime import datetime, timezone

# --- Test Ayarları ---
# Testin bağlanacağı, çalışan FastAPI uygulamasının adresi.
TEST_APP_URL = "http://127.0.0.1:8000/verify-wifi"

# ipconfig çıktısından alınan gerçek WiFi IP adresiniz.
YOUR_REAL_WIFI_IP = "192.168.1.117"

# --- Testler için Fixture'lar ---

@pytest.fixture
def correct_ip_attendance_payload():
    """Doğru IP adresine sahip (SİZİN IP'niz) bir yoklama nesnesinin JSON verisini oluşturur."""
    return {
        "attendance_id": str(uuid.uuid4()),
        "teacher_school_number": "T-REAL-01",
        "lesson_name": "Gerçek WiFi Testi",
        "ip_address": YOUR_REAL_WIFI_IP,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "security_option": 1
    }

@pytest.fixture
def incorrect_ip_attendance_payload():
    """Yanlış IP adresine sahip bir yoklama nesnesinin JSON verisini oluşturur."""
    return {
        "attendance_id": str(uuid.uuid4()),
        "teacher_school_number": "T-REAL-02",
        "lesson_name": "Yanlış WiFi Testi",
        "ip_address": "10.10.10.10", # Farklı bir IP
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(),
        "security_option": 1
    }

# --- Test Senaryoları ---

@pytest.mark.asyncio
async def test_wifi_verification_with_matching_ip(correct_ip_attendance_payload):
    """
    Doğru yoklama verisi ve header ile simüle edilmiş doğru IP gönderildiğinde
    doğrulamanın başarılı olmasını test eder.
    """
    # DÜZELTME: İsteği gönderirken 'X-Forwarded-For' header'ını ekleyerek
    # gerçek bir proxy'den geliyormuş gibi sizin IP'nizi simüle ediyoruz.
    headers = {"X-Forwarded-For": YOUR_REAL_WIFI_IP}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(TEST_APP_URL, json=correct_ip_attendance_payload, headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["is_wifi_valid"] is True
    assert data["checked_ip"] == YOUR_REAL_WIFI_IP

@pytest.mark.asyncio
async def test_wifi_verification_with_mismatching_ip(incorrect_ip_attendance_payload):
    """
    Yanlış yoklama verisi gönderildiğinde, doğrulamanın başarısız olmasını test eder.
    """
    headers = {"X-Forwarded-For": YOUR_REAL_WIFI_IP}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(TEST_APP_URL, json=incorrect_ip_attendance_payload, headers=headers)
        
    assert response.status_code == 200
    data = response.json()
    assert data["is_wifi_valid"] is False
    assert data["checked_ip"] == YOUR_REAL_WIFI_IP
