from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://logbook:logbook@localhost:5432/logbook"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 100
    # Photos larger than this (long edge in pixels, or file size) are downscaled
    # and re-encoded as JPEG; see backend/images.py
    PHOTO_MAX_PX: int = 2560
    PHOTO_MAX_MB: float = 2.0
    PHOTO_JPEG_QUALITY: int = 85
    THUMB_PX: int = 480
    APP_TITLE: str = "Thin Film Logbook"
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    BASE_URL: str = "http://localhost:8000"  # override in production

    # Email (Gmail SMTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "sample.logbook@gmail.com"
    SMTP_PASSWORD: str = ""          # set via SMTP_PASSWORD env var or .env
    EMAIL_FROM_NAME: str = "CTN Logbook"

    class Config:
        env_file = BASE_DIR / ".env"

settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
