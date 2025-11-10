# tests/tools/test_app.py

from fastapi import FastAPI, Request, HTTPException
from typing import Optional
from uuid import UUID
from datetime import datetime

# Gerçek `verify_wifi` fonksiyonunu import ediyoruz
from app.backend.tools.wifi_verifier import verify_wifi
# Doğrudan `Attendance` modelini import ediyoruz
from app.backend.models.db_models import Attendance

# Bu, test sırasında çalışacak olan mini sunucumuzdur.
app = FastAPI()

@app.post("/verify-wifi")
async def verify_wifi_endpoint(attendance: Attendance, request: Request):
    """
    Bu endpoint, bir `Attendance` nesnesini doğrudan body'den alır ve
    isteği yapan client'ın gerçek IP adresiyle karşılaştırır.
    """
    try:
        # DÜZELTME: Gerçek bir sunucu ortamını simüle etmek için,
        # önce 'X-Forwarded-For' header'ını kontrol ediyoruz. Bu, en doğru yöntemdir.
        client_ip = request.headers.get("x-forwarded-for", request.client.host)

        # Ana fonksiyonumuzu çağır
        is_valid = verify_wifi(attendance, client_ip)
        
        return {"is_wifi_valid": is_valid, "checked_ip": client_ip, "session_ip": attendance.ip_address}

    except Exception as e:
        print(f"Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Bu dosyayı doğrudan çalıştırdığında, sunucu 8000 portunda başlar.
    # python tests/tools/test_app.py
    uvicorn.run(app, host="0.0.0.0", port=8000)