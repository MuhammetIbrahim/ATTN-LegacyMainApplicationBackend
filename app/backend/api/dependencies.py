#app/backend/api/dependencies.py
from fastapi import Request,Depends
import redis.asyncio as redis
import asyncpg

# Servis ve istemci sınıflarını import etmemiz gerekiyor
from ..db.redis_client import RedisClient
from ..db.db_client import AsyncPostgresClient
from ..services.teacher_service import TeacherService
from ..services.student_service import StudentService # YENİ: StudentService import edildi


def get_redis_pool(request: Request) -> redis.ConnectionPool:
    """
    Uygulamanın state'inden Redis bağlantı havuzunu alır ve bir bağımlılık olarak sağlar.
    """
    return request.app.state.redis_pool

def get_postgres_pool(request: Request) -> asyncpg.Pool:
    """
    Uygulamanın state'inden PostgreSQL bağlantı havuzunu alır ve bir bağımlılık olarak sağlar.
    """
    return request.app.state.postgres_pool


def get_teacher_service(
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool),
    postgres_pool: asyncpg.Pool = Depends(get_postgres_pool)
) -> TeacherService:
    """
    Her istek için yeni bir TeacherService nesnesi oluşturur.
    
    Bu fonksiyon, FastAPI'nin Bağımlılık Enjeksiyonu sistemi tarafından kullanılır.
    Her endpoint çağrıldığında, FastAPI bu fonksiyonu çalıştırır. Fonksiyon,
    uygulama başlangıcında oluşturulan paylaşımlı bağlantı havuzlarını (pools)
    kullanarak yeni istemci ve servis nesneleri oluşturur ve bunları endpoint'e verir.
    """
    # 1. Paylaşımlı havuzları kullanarak istemcileri (clients) oluştur
    redis_client = RedisClient(pool=redis_pool)
    db_client = AsyncPostgresClient(pool=postgres_pool)
    
    # 2. İstemcileri kullanarak servisi oluştur ve döndür
    return TeacherService(redis_client=redis_client, db_client=db_client)


def get_student_service(
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool),
    postgres_pool: asyncpg.Pool = Depends(get_postgres_pool)
) -> StudentService:
    """
    Her istek için yeni bir StudentService nesnesi oluşturur.
    
    TeacherService ile aynı mantıkla çalışır: Paylaşımlı havuzları kullanarak
    her istek için taze bir servis nesnesi yaratır ve bunu öğrenci endpoint'lerine
    sağlar.
    """
    redis_client = RedisClient(pool=redis_pool)
    db_client = AsyncPostgresClient(pool=postgres_pool)
    
    return StudentService(redis_client=redis_client, db_client=db_client)



async def get_client_ip(request: Request) -> str | None:
    """
    İstemcinin gerçek IP adresini proxy başlıklarından okur.
    Nginx, CloudFlare gibi proxy'ler için çoklu başlık desteği.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Debug: Log all headers to see what's available
    logger.info(f"All request headers: {dict(request.headers)}")
    
    # Try multiple headers in order of preference
    for header_name in ["cf-connecting-ip", "x-real-ip", "x-forwarded-for"]:
        header = request.headers.get(header_name)
        if header:
            # X-Forwarded-For can be "client, proxy1, proxy2" - take the first (leftmost) IP
            client_ip = header.split(",")[0].strip()
            logger.info(f"Found client IP '{client_ip}' from header '{header_name}': '{header}'")
            return client_ip
    
    # Fallback to direct connection IP
    direct_ip = request.client.host if request.client else None
    logger.info(f"Using direct client IP: '{direct_ip}'")
    return direct_ip