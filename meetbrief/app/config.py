"""Small, explicit environment configuration for Meetbrief."""
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "meetbrief.db")
    app_secret: str = os.getenv("APP_SECRET", "local-demo-secret-change-before-sharing")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_MB", "5")) * 1024 * 1024
    max_transcript_chars: int = int(os.getenv("MAX_TRANSCRIPT_CHARS", "500000"))
    session_hours: int = int(os.getenv("SESSION_HOURS", "12"))
    retention_days: int = int(os.getenv("RETENTION_DAYS", "0"))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    llm_max_chars: int = int(os.getenv("MAX_LLM_CHARS", "80000"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def database_file(self) -> Path:
        return Path(self.database_path).expanduser()


settings = Settings()
