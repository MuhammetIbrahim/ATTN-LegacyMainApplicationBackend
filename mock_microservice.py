from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
import uuid

app = FastAPI(
    title="Asynchronous Face Verifier Microservice (Stub)",
    description="Accepts face verification jobs and immediately returns a 202 Accepted status.",
    version="4.0.0-stub"
)

@app.post("/verify-face-async")
async def verify_face_asynchronously(
    # Form verilerini alıyoruz, ancak henüz kullanmıyoruz
    webhook_url: str = Form(...),
    verification_id: str = Form(...),
    # Dosyaları alıyoruz, ancak henüz kullanmıyoruz
    picture: UploadFile = File(...),
    intended_picture: UploadFile = File(...)
):
    """
    Bu endpoint, yüz tanıma işini kabul eder ve anında 202 (Accepted) yanıtı döner.
    Bu versiyonda, gelen verilerle herhangi bir işlem YAPMAZ.
    Sadece ana uygulamanın doğru istek gönderip göndermediğini test etmek için kullanılır.
    """
    # Gelen dosyaların content-type'ını kontrol etmek gibi basit doğrulamalar yapılabilir
    if picture.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=415, detail="Invalid content type for picture.")
    if intended_picture.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=415, detail="Invalid content type for intended_picture.")

    # Hiçbir işlem yapmadan, işi kabul ettiğimize dair bir yanıt dönüyoruz.
    return JSONResponse(
        status_code=202,
        content={"status": "Job accepted", "verification_id": verification_id}
    )

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
