# app/backend/modules/aksis.py

import httpx
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
import re
import base64
import logging # Loglama için gerekli modülü import ediyoruz.
from typing import Dict, Any, List, Optional
from ..config.config import settings
from .lesson_finder import find_lessons_for_day

# Bu modül için özel bir logger oluşturuyoruz.
logger = logging.getLogger(__name__)

# Custom exceptions for clearer error handling
class AksisAuthError(Exception):
    """Raised when login credentials are incorrect."""
    pass

class AksisSessionError(Exception):
    """Raised for issues related to the Aksis session."""
    pass


class AksisClient:
    """
    Client for interacting with the Aksis system.
    Uses injected HTTP client to ensure complete session isolation between users.
    """

    def __init__(self, school_number: str, password: str, http_client: httpx.AsyncClient):
        self._school_number = school_number
        self._password = password
        # Injected HTTP client with isolated cookies for this specific user session
        self._client = http_client

    async def login(self) -> Dict[str, str]:
        """
        Logs into Aksis and returns user information.
        Raises AksisAuthError on failure.
        """
        logger.info(f"Kullanıcı '{self._school_number}' için Aksis'e giriş işlemi deneniyor.")
        client = self._client
        try:
            # 1. Get the login page to retrieve the verification token
            response = await client.get(settings.AKSIS_LOGIN_URL)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            token_input = soup.find('input', {'name': '__RequestVerificationToken'})
            if not token_input:
                logger.error("Aksis login sayfasında __RequestVerificationToken bulunamadı.")
                raise AksisSessionError("Login sayfasından doğrulama anahtarı alınamadı.")
            token = token_input['value']

            # 2. Post the login credentials
            login_data = {
                "UserName": self._school_number,
                "Password": self._password,
                "__RequestVerificationToken": token
            }
            response = await client.post(settings.AKSIS_LOGIN_URL, data=login_data)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 3. Check for login errors on the new page
            if soup.find("div", "validation-summary-errors"):
                logger.warning(f"Kullanıcı '{self._school_number}' için geçersiz parola veya kullanıcı adı.")
                raise AksisAuthError("Kullanıcı adı veya şifre hatalı.")

            # 4. Determine the user's role and return appropriate data
            if soup.find("h4", string="ÖYS AKADEMİSYEN"):
                raw_name_tag = soup.find("h5", class_="m-t-0 m-b-0")
                raw_name = raw_name_tag.text if raw_name_tag else ""
                name_list = raw_name.split(".")
                full_name = name_list[-1].strip() if name_list else ""
                logger.info(f"Kullanıcı '{self._school_number}' öğretmen olarak başarıyla giriş yaptı.")
                return {"role": "Teacher", "full_name": full_name, "school_number": self._school_number}
            else:
                logger.info(f"Kullanıcı '{self._school_number}' öğrenci olarak başarıyla giriş yaptı.")
                return {"role": "Student"}

        except httpx.RequestError as e:
            logger.error(f"Aksis'e bağlanırken ağ hatası oluştu: {e}", exc_info=True)
            raise AksisSessionError("Aksis servisine bağlanırken bir ağ sorunu yaşandı.")
        except Exception as e:
            logger.error(f"Giriş işlemi sırasında beklenmedik bir hata oluştu: {e}", exc_info=True)
            if isinstance(e, (AksisAuthError, AksisSessionError)):
                raise
            raise AksisSessionError(f"Giriş sırasında beklenmedik bir hata oluştu: {e}")

    async def get_obs_profile(self) -> Dict[str, Any]:
        """
        Navigates to the OBS profile page and extracts user details.
        """
        logger.info(f"Kullanıcı '{self._school_number}' için OBS profil bilgileri çekiliyor.")
        client = self._client
        try:
            response = await client.get(settings.AKSIS_OBS_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            full_name_tag = soup.find("th", string="Ad Soyad")
            school_number_tag = soup.find("th", string="Numara")
            image_tag = "img"

            if not all([full_name_tag, school_number_tag, image_tag]):
                logger.error(f"Kullanıcı '{self._school_number}' için OBS profil sayfasında gerekli tüm elementler bulunamadı.")
                raise AksisSessionError("Profil sayfasındaki tüm gerekli bilgiler bulunamadı.")

            full_name = full_name_tag.find_next_sibling("td").text
            school_number = school_number_tag.find_next_sibling("td").text
            image_url = "sdfdsfsdfdsdsfsdffs"
            
            logger.info(f"Kullanıcı '{self._school_number}' için OBS profil bilgileri başarıyla çekildi.")
            return {"full_name": full_name, "school_number": school_number, "image_url": image_url}
        except httpx.RequestError as e:
            logger.error(f"OBS profili çekilirken ağ hatası: {e}", exc_info=True)
            raise AksisSessionError("Aksis OBS profiline bağlanırken bir ağ sorunu yaşandı.")
        except Exception as e:
            logger.error(f"OBS profili parse edilirken beklenmedik bir hata: {e}", exc_info=True)
            raise AksisSessionError(f"Profil bilgileri işlenirken beklenmedik bir hata oluştu: {e}")

    async def get_daily_schedule(self, target_date: datetime) -> List[Dict[str, Any]]:
        """
        Fetches the user's weekly schedule and filters it for a specific day.
        """
        logger.info(f"Kullanıcı '{self._school_number}' için '{target_date.strftime('%Y-%m-%d')}' tarihli ders programı çekiliyor.")
        client = self._client
        try:
            response = await client.get(settings.AKSIS_LESSON_SCHEDULE_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            script_content = "".join(script.text for script in soup.find_all("script"))
            
            match = re.search(r'Plans_Read\?[^"\']*', script_content)
            if not match:
                logger.warning(f"Kullanıcı '{self._school_number}' için ders programı verisi bulunamadı.")
                return []
            
            dynamic_url_path = match.group(0).replace("\\u0026", "&")
            full_schedule_url = f"{settings.AKSIS_OBS_URL}OgrenimBilgileri/DersProgramiYeni/{dynamic_url_path}"

            response = await client.post(full_schedule_url)
            response.raise_for_status()
            json_data = response.json()
            
            daily_lessons = find_lessons_for_day(json_data.get("Data", []), target_date)
            logger.info(f"Kullanıcı '{self._school_number}' için {len(daily_lessons)} adet ders bulundu.")
            return daily_lessons
        except httpx.RequestError as e:
            logger.error(f"Ders programı çekilirken ağ hatası: {e}", exc_info=True)
            raise AksisSessionError("Aksis ders programına bağlanırken bir ağ sorunu yaşandı.")
        except Exception as e:
            logger.error(f"Ders programı işlenirken beklenmedik bir hata: {e}", exc_info=True)
            raise AksisSessionError(f"Ders programı işlenirken beklenmedik bir hata oluştu: {e}")

    async def get_profile_image_base64(self, image_url: str) -> str:
        """
        Downloads an image from a URL and returns it as a base64 encoded string.
        """
        logger.info(f"Profil resmi indiriliyor: {image_url}")
        client = self._client
        try:
            response = await client.get(image_url)
            response.raise_for_status()
            logger.info(f"Profil resmi başarıyla indirildi.")
            return base64.b64encode(response.content).decode('utf-8')
        except httpx.RequestError as e:
            logger.error(f"Profil resmi indirilirken ağ hatası: {e}", exc_info=True)
            raise AksisSessionError("Profil resmi indirilirken bir ağ sorunu yaşandı.")
        except Exception as e:
            logger.error(f"Profil resmi Base64'e çevrilirken hata: {e}", exc_info=True)
            raise AksisSessionError(f"Profil resmi işlenirken bir hata oluştu: {e}")

    # Note: HTTP client lifecycle is managed by the caller
    # AksisClient no longer manages client lifecycle
