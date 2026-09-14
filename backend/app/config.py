from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os, secrets

BASE_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'college_grievance.db').as_posix()}"
    upload_dir: str = str(BASE_DIR / "uploads")
    cors_origins: str = "http://127.0.0.1:5500,http://localhost:5500"
    escalation_days: int = 14
    max_audio_mb: int = 10
    token_expiry_minutes: int = 30
    refresh_expiry_days: int = 7
    jwt_secret: str = ""
    developer_mode: bool = False
    developer_key: str = ""
    bootstrap_admin_id: str = "admin001"
    bootstrap_admin_name: str = "System Administrator"
    bootstrap_admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

# A random secret is safe for a local demo. Production deployments must set JWT_SECRET.
if not settings.jwt_secret:
    settings.jwt_secret = secrets.token_urlsafe(48)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
