# app/backend/main.py
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import redis.asyncio as redis
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler as Scheduler
import logging

# Rate limiting için gerekli importlar
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Proje ayarlarını ve modüllerini import edelim
from .config.config import settings
from .api import auth, teacher, student,webhooks

# Gerekli istemci ve görev (task) fonksiyonlarını import edelim
from .db.redis_client import RedisClient
from .db.db_client import AsyncPostgresClient
from .tasks.cron import  unified_persistence_task

from .api.utilities.limiter import limiter

# Logging yapılandırması
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#adding empty cors for building frontend
from fastapi.middleware.cors import CORSMiddleware




@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Uygulama başlatıldığında ve durdurulduğunda çalışacak olan yaşam döngüsü yöneticisi.
    """
    # Rate limiter'ı uygulama state'ine ekle
    app.state.limiter = limiter
    
    logger.info("Uygulama başlatılıyor...")
    
    postgres_pool = None
    redis_pool = None
    scheduler = None

    try:
        postgres_pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL, min_size=5, max_size=20
        )
        redis_pool = redis.ConnectionPool.from_url(
            settings.APPLICATION_REDIS_URL, decode_responses=True
        )
        
        app.state.postgres_pool = postgres_pool
        app.state.redis_pool = redis_pool
        logger.info("PostgreSQL ve Redis bağlantı havuzları başarıyla oluşturuldu.")

        db_client = AsyncPostgresClient(pool=postgres_pool)
        redis_client = RedisClient(pool=redis_pool)
        
        
        scheduler = Scheduler()
        scheduler.add_job(unified_persistence_task, "interval", minutes=5, args=[redis_client, db_client], id="sweep_attendances")
        scheduler.start()
        
        app.state.scheduler = scheduler
        logger.info("Zamanlanmış görevler (cron jobs) başarıyla başlatıldı.")

    except Exception as e:
        logger.error(f"HATA: Başlangıç sırasında bir hata oluştu: {e}")
        # Hata durumunda state'i temizle
        app.state.postgres_pool = None
        app.state.redis_pool = None
        app.state.scheduler = None

    yield

    logger.info("Uygulama kapatılıyor...")
    if hasattr(app.state, 'scheduler') and app.state.scheduler:
        await app.state.scheduler.shutdown()
        logger.info("Scheduler kapatıldı.")
    if hasattr(app.state, 'postgres_pool') and app.state.postgres_pool:
        await app.state.postgres_pool.close()
        logger.info("PostgreSQL bağlantı havuzu kapatıldı.")
    if hasattr(app.state, 'redis_pool') and app.state.redis_pool:
        await app.state.redis_pool.disconnect()
        logger.info("Redis bağlantı havuzu kapatıldı.")


# Ana FastAPI uygulamasını oluştur
app = FastAPI(
    title="ATTN API",
    description="Yoklama ve Öğrenci Yönetim Sistemi API'si",
    version="1.0.0",
    lifespan=lifespan
)

origins = [
   "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limit aşıldığında çalışacak hata yöneticisini ekle
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# API router'larını uygulamaya dahil et
app.include_router(auth.router, prefix="/api/v1")
app.include_router(teacher.router, prefix="/api/v1")
app.include_router(student.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")

@app.get("/health", tags=["System"])
def health_check():
    """Uygulamanın ayakta ve sağlıklı olup olmadığını kontrol etmek için basit bir endpoint."""
    return {"status": "ok", "message": "ATTN API is running."}

