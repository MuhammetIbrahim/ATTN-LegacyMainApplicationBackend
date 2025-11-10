# app/backend/api/utilities/limiter.py

from fastapi import Request
import jwt

# Gerekli slowapi ve ayar importları
from slowapi import Limiter
from slowapi.util import get_remote_address

# config.py'den ayarları import et
from ...config.config import settings

def get_limiter_key(request: Request) -> str:
    """
    Rate limit için bir anahtar döndürür.
    Eğer istekte geçerli bir JWT token varsa, kullanıcı okul numarasını anahtar olarak kullanır.
    Yoksa, istemcinin IP adresini kullanır. Bu, hem giriş yapmış hem de yapmamış
    kullanıcılar için esnek bir limit stratejisi sağlar.
    """
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ")[1]
        try:
            # Token'ın süresinin dolup dolmadığını kontrol etmeye gerek yok,
            # sadece içindeki kullanıcı kimliğini almak istiyoruz.
            payload = jwt.decode(
                token, 
                settings.SECRET_KEY, 
                algorithms=[settings.ALGORITHM], 
                options={"verify_exp": False}
            )
            user_school_number: str = payload.get("user_school_number")
            if user_school_number:
                return user_school_number
        except jwt.PyJWTError:
            # Token geçersizse veya decode edilemezse, IP bazlı limite geri dön.
            pass
            
    # Güvenli fallback: Her zaman bir anahtar döndür.
    return get_remote_address(request)

# Limiter'ı Redis depolaması ile başlat.
# NOT: config.py dosyanıza RATE_LIMITER_REDIS_URL="redis://localhost:6379/1" gibi
#      yeni bir ayar eklediğinizden emin olun.
limiter = Limiter(key_func=get_limiter_key, storage_uri=settings.RATE_LIMITER_REDIS_URL)
