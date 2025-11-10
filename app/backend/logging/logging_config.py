import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Projenin ana dizininde bir 'logs' klasörü oluştur (varsa es geçer)
# Docker volume ile bu klasörü sunucudaki kalıcı bir dizine bağlayacağız.
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)


def setup_logging():
    """
    Uygulama genelinde kullanılacak olan merkezi loglama yapılandırmasını kurar.

    Bu fonksiyon, logları hem konsola (geliştirme için) hem de belirli bir boyuta
    ulaştığında otomatik olarak eskiyen/dönen bir dosyaya (üretim ortamı için) yazar.
    """
    # Log mesajlarımızın formatını belirliyoruz: Zaman - Modül Adı - Seviye - Mesaj
    log_format = "%(asctime)s - [%(name)s] - %(levelname)s - %(message)s"
    
    # Kök logger'ı alıyoruz, tüm loglama bu logger üzerinden dallanacak.
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # Sadece INFO ve üzeri seviyedeki logları işle.
    
    # Uvicorn gibi kütüphanelerin varsayılan handler'larını temizleyerek
    # kendi standart formatımızı zorunlu kılıyoruz.
    if logger.hasHandlers():
        logger.handlers.clear()

    # 1. Konsol Handler: Logları terminale (standart çıktıya) yazar.
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(stdout_handler)

    # 2. Dönen Dosya Handler: Logları bir dosyaya yazar.
    # Dosya boyutu 5MB'ı geçtiğinde, eski logları app.log.1, app.log.2
    # gibi dosyalara taşıyarak yeni bir log dosyası oluşturur.
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=5          # En fazla 5 eski log dosyası tut
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)
