import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[1] / "config.env"
load_dotenv(ENV_PATH)


def _local_jwt_secret() -> str:
    configured = os.getenv("JWT_SECRET_KEY")
    if configured:
        return configured
    secret_path = ENV_PATH.parent / "data" / ".jwt-secret"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        return secret_path.read_text(encoding="ascii").strip()
    value = secrets.token_hex(32)
    secret_path.write_text(value, encoding="ascii")
    return value


class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "mistralai/ministral-8b-2512")
    sqlite_path: str = os.getenv(
        "SQLITE_PATH",
        str(ENV_PATH.parent / "data" / "study_buddy.db"),
    )
    redis_url: str    = os.getenv("REDIS_URL", "")

    model_name: str = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")
    transformers_no_tf: str = os.getenv("TRANSFORMERS_NO_TF", "1")
    cors_allowed_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    local_arabic_nsfw_words: list[str] = [
        w.strip()
        for w in os.getenv("LOCAL_ARABIC_NSFW_WORDS", "").split(",")
        if w.strip()
    ]
    local_nsfw_words: list[str] = [
        w.strip()
        for w in os.getenv("LOCAL_NSFW_WORDS", "").split(",")
        if w.strip()
    ]

    # ── JWT / Refresh-Token Auth ───────────────────────────────────────────────
    jwt_secret_key: str = _local_jwt_secret()
    jwt_algorithm: str  = os.getenv("JWT_ALGORITHM", "HS256")
    # Set to 'development' locally so Secure cookie flag is not required over HTTP
    environment: str    = os.getenv("ENVIRONMENT", "development")


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    if s.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = s.gemini_api_key
    if s.openrouter_api_key:
        os.environ["OPENROUTER_API_KEY"] = s.openrouter_api_key
    if "TRANSFORMERS_NO_TF" not in os.environ and s.transformers_no_tf:
        os.environ["TRANSFORMERS_NO_TF"] = s.transformers_no_tf
    return s


settings = get_settings()
