import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Ortam değişkenlerinden ayarları doğrudan ve basit bir şekilde tutan sınıf.
    """
    # Veritabanı
    DATABASE_URL: str = os.environ.get("DATABASE_URL")

    # --- DOĞRU REDIS AYARI ---
    APPLICATION_REDIS_URL: str = os.environ.get("APPLICATION_REDIS_URL")
    RATE_LIMITER_REDIS_URL: str = os.environ.get("RATE_LIMITER_REDIS_URL")
    # Aksis, JWT ve diğer ayarlar...
    AKSIS_LOGIN_URL: str = os.environ.get("AKSIS_LOGIN_URL")
    AKSIS_OBS_URL: str = os.environ.get("AKSIS_OBS_URL")
    AKSIS_LESSON_SCHEDULE_URL: str = os.environ.get("AKSIS_LESSON_SCHEDULE_URL")
    FACE_VERIFIER_MICROSERVICE_URL: str = os.environ.get("FACE_VERIFIER_MICROSERVICE_URL")
    MAIN_APP_BASE_URL: str = os.environ.get("MAIN_APP_BASE_URL", "http://localhost:8000")
    AKSIS_STUDENT_USERNAME: str = os.environ.get("AKSIS_STUDENT_USERNAME")
    AKSIS_STUDENT_PASSWORD: str = os.environ.get("AKSIS_STUDENT_PASSWORD")
    SECRET_KEY: str = os.environ.get("SECRET_KEY")
    WEBHOOK_SECRET_KEY: str = os.environ.get("WEBHOOK_SECRET_KEY")
    ALGORITHM: str = os.environ.get("ALGORITHM")
    STUDENT_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("STUDENT_TOKEN_EXPIRE_MINUTES", 15))
    TEACHER_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("TEACHER_TOKEN_EXPIRE_MINUTES", 60))
    TEACHER_SESSION_TTL_SECONDS: int = int(os.environ.get("TEACHER_SESSION_TTL_SECONDS", 3600))
    STUDENT_SESSION_TTL_SECONDS: int = int(os.environ.get("STUDENT_SESSION_TTL_SECONDS", 600))

# Ayarların tek ve içe aktarılabilir bir örneğini oluştur
settings = Config()