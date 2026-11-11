"""Configuration centralisée, lue depuis les variables d'environnement / .env."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Un seul fichier .env, à la racine du dépôt (partagé avec Docker Compose)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PayPredict AI"
    environment: str = "development"

    postgres_user: str = "paypredict"
    postgres_password: str = Field(default="change_me")
    postgres_db: str = "paypredict"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    # --- sécurité (phase 3) ---
    jwt_secret: str = "dev-only-change-me-use-a-long-random-string-0123456789"
    access_token_minutes: int = 60
    automation_api_key: str = "dev-only-automation-key-change-me" # clé partagée avec n8n
    cors_origins: str = "http://localhost:5173" # séparées par des virgules
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()