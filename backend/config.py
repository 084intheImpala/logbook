from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://logbook:logbook@localhost:5432/logbook"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 100
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
