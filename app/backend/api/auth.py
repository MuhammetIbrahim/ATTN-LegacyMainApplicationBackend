import logging
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Optional
import jwt
import redis.asyncio as redis
import httpx
from pydantic import ValidationError

# Gerekli tüm şemaları, modülleri, modelleri ve bağımlılıkları import edelim
from .schemas.user import Token, TokenData, LoginRequest, UserResponse, LoginResponse
from ..modules.aksis import AksisClient, AksisAuthError, AksisSessionError
from ..models.db_models import User
# --- Refactor Değişikliği: UserRedis -> UserSessionRedis ---
from ..models.redis_models import UserSessionRedis
from ..db.redis_client import RedisClient
from ..config.config import settings
from .dependencies import get_redis_pool
from .utilities.limiter import limiter

# Bu modül için özel bir logger oluşturuyoruz.
logger = logging.getLogger(__name__)

# --- Router ve Güvenlik Kurulumu ---
router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# --- Yardımcı Fonksiyonlar ---
def create_access_token(data: dict, expires_delta: timedelta):
    """Verilen data ve süre ile yeni bir JWT access token oluşturur."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


# --- Korunmuş Rotalar için Bağımlılık (GÜNCELLENDİ) ---
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool)
) -> User:
    """
    Token'ı decode eder, Pydantic ile doğrular, Redis'te aktif bir oturum 
    olup olmadığını kontrol eder ve güncel User nesnesini döndürür.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # --- Pydantic ile Doğrulama ---
        # Gelen token içeriğini TokenData modeli ile doğruluyoruz.
        # Bu, token'ın beklenen yapıda olduğunu garanti eder.
        token_data = TokenData.model_validate(payload)
        
        if token_data.user_school_number is None:
            logger.warning(f"Token is valid but missing 'user_school_number': {payload}")
            raise credentials_exception
        
        # --- Redis Oturum Kontrolü ---
        redis_client = RedisClient(pool=redis_pool)
        user_session = await redis_client.get_user_session(token_data.user_school_number)
        
        if user_session is None:
            logger.warning(f"User '{token_data.user_school_number}' has a valid token but no active session in Redis. Denying access.")
            raise credentials_exception
            
        # Her zaman Redis'teki en güncel kullanıcı verisini döndür
        return user_session.user_data
        
    except (jwt.PyJWTError, ValidationError) as e:
        # Hem JWT hatalarını (süre dolması, imza hatası) hem de Pydantic doğrulama
        # hatalarını (eksik alan, yanlış tip) yakalıyoruz.
        logger.warning(f"Token validation error: {e}")
        raise credentials_exception


# --- Merkezi Login Mantığı (YENİDEN YAPILANDIRILDI) ---

async def _handle_demo_login(username: str, password: str, redis_client: RedisClient) -> Optional[LoginResponse]:
    """Demo kullanıcılar için giriş mantığını yönetir. Artık 10 öğretmen ve 10 öğrenci oluşturur."""
    if password != "password":
        return None

    # Demo öğretmenleri (demo_teacher_1 to demo_teacher_10)
    if username.startswith("demo_teacher_"):
        try:
            user_id = int(username.split('_')[-1])
            if 1 <= user_id <= 10:
                school_number = username
                role = "Teacher"
                user_data = User(user_school_number=school_number, user_full_name=f"Demo Teacher {user_id}", role=role)
                
                # --- Refactor Değişikliği: TTL ile oturum kaydı ---
                ttl = settings.TEACHER_SESSION_TTL_SECONDS
                redis_session = UserSessionRedis(user_data=user_data, session_id=uuid4(), session_start_time=datetime.now(timezone.utc), session_end_time=datetime.now(timezone.utc) + timedelta(seconds=ttl))
                await redis_client.save_user_session(redis_session, ttl=ttl)
                
                token_payload = {"user_school_number": school_number} # Sadeleştirilmiş payload
                access_token = create_access_token(data=token_payload, expires_delta=timedelta(seconds=ttl))
                return LoginResponse(token=Token(access_token=access_token, token_type="bearer"), user=UserResponse.model_validate(user_data), schedule=None)
        except (ValueError, IndexError):
            return None # Geçersiz format

    # Demo öğrenciler (demo_student_1 to demo_student_10)
    if username.startswith("demo_student_"):
        try:
            user_id = int(username.split('_')[-1])
            if 1 <= user_id <= 10:
                school_number = username
                role = "Student"
                user_data = User(user_school_number=school_number, user_full_name=f"Demo Student {user_id}", role=role)
                
                # --- Refactor Değişikliği: TTL ile oturum kaydı ---
                ttl = settings.STUDENT_SESSION_TTL_SECONDS
                redis_session = UserSessionRedis(user_data=user_data, session_id=uuid4(), session_start_time=datetime.now(timezone.utc), session_end_time=datetime.now(timezone.utc) + timedelta(seconds=ttl), image_url=f"https://placehold.co/150x150/EFEFEF/333?text=DS{user_id}")
                await redis_client.save_user_session(redis_session, ttl=ttl)
                
                token_payload = {"user_school_number": school_number} # Sadeleştirilmiş payload
                access_token = create_access_token(data=token_payload, expires_delta=timedelta(seconds=ttl))
                demo_schedule = [{"lesson_name": "Yazılım Mühendisliği", "teacher_name": "Dr. Ada Lovelace", "start_time": "09:00", "end_time": "11:00"}]
                return LoginResponse(token=Token(access_token=access_token, token_type="bearer"), user=UserResponse.model_validate(user_data), schedule=demo_schedule)
        except (ValueError, IndexError):
            return None

    return None

async def _perform_login(username: str, password: str, redis_pool: redis.ConnectionPool) -> LoginResponse:
    """Tüm giriş mantığını yürüten merkezi fonksiyon."""
    logger.info(f"Login attempt for user '{username}'.")
    redis_client = RedisClient(pool=redis_pool)

    try:
        if "demo" in username:
            demo_response = await _handle_demo_login(username, password, redis_client)
            if demo_response:
                logger.info(f"Demo user '{username}' logged in successfully.")
                return demo_response

        # Isolated HTTP client for this specific login session
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            cookies=httpx.Cookies(),  # Fresh cookie jar for complete isolation
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        ) as http_client:
            aksis_client = AksisClient(school_number=username, password=password, http_client=http_client)
            user_info = await aksis_client.login()
            role = user_info.get("role")
            
            image_url, daily_schedule = None, None
            school_number, full_name = "", ""

            if role == "Teacher":
                school_number = user_info.get("school_number", username)
                full_name = user_info.get("full_name", "Unknown Teacher")
                ttl = settings.TEACHER_SESSION_TTL_SECONDS
            elif role == "Student":
                profile_data = await aksis_client.get_obs_profile()
                school_number = profile_data.get("school_number", username)
                full_name = profile_data.get("full_name", "Unknown Student")
                image_url = profile_data.get("image_url")
                daily_schedule = await aksis_client.get_daily_schedule(datetime.now(timezone(timedelta(hours=3))))
                ttl = settings.STUDENT_SESSION_TTL_SECONDS
            else:
                logger.error(f"Unexpected role from Aksis: {role}")
                raise HTTPException(status_code=403, detail="Unknown user role from Aksis.")

            user_data = User(user_school_number=school_number, user_full_name=full_name, role=role)
            
            # --- Refactor Değişikliği: UserSessionRedis ve TTL kullanımı ---
            redis_session = UserSessionRedis(user_data=user_data, session_id=uuid4(), session_start_time=datetime.now(timezone.utc), session_end_time=datetime.now(timezone.utc) + timedelta(seconds=ttl), image_url=image_url)
            await redis_client.save_user_session(redis_session, ttl=ttl)
            logger.info(f"Redis session created for user '{username}' with a TTL of {ttl} seconds.")

            # --- Refactor Değişikliği: Sadeleştirilmiş token payload ---
            token_payload = {"user_school_number": school_number}
            access_token = create_access_token(data=token_payload, expires_delta=timedelta(seconds=ttl))
            
            logger.info(f"User '{username}' ({role}) logged in successfully.")
            return LoginResponse(token=Token(access_token=access_token, token_type="bearer"), user=UserResponse.model_validate(user_data), schedule=daily_schedule)

    except AksisAuthError:
        logger.warning(f"Aksis authentication failed for user '{username}' (invalid credentials).")
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    except AksisSessionError as e:
        logger.error(f"Aksis service session error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Aksis service is currently unavailable.")
    except Exception as e:
        logger.error(f"Unexpected error during login: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected server error occurred during login.")


# --- API Endpoint'leri ---

@router.post("/token", response_model=Token)
@limiter.limit("2000/minute")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool)
):
    """Standard OAuth2 endpoint for Swagger UI."""
    login_response = await _perform_login(form_data.username, form_data.password, redis_pool)
    return login_response.token


@router.post("/login", response_model=LoginResponse)
@limiter.limit("2000/minute")
async def login(
    request: Request,
    login_request: LoginRequest,
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool)
):
    """Login endpoint for mobile/web clients."""
    return await _perform_login(login_request.username, login_request.password, redis_pool)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("2000/minute")
async def logout(
    request: Request,
    redis_pool: redis.ConnectionPool = Depends(get_redis_pool),
    current_user: User = Depends(get_current_user)
):
    """User logout, deletes the session from Redis."""
    logger.info(f"User '{current_user.user_school_number}' logging out.")
    try:
        redis_client = RedisClient(pool=redis_pool)
        # --- Refactor Değişikliği: Yeni metot adı ---
        await redis_client.delete_user_session(current_user.user_school_number)
        logger.info(f"Session for user '{current_user.user_school_number}' successfully deleted from Redis.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error during logout for user '{current_user.user_school_number}'.", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred during logout.")
