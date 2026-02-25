from pathlib import Path

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # HubSpot
    hubspot_token: str
    hubspot_portal_id: int

    # Holded
    holded_api_key: str

    # Google
    google_client_secret_path: Path

    # Slack
    slack_bot_token: str

    # Admin
    admin_email: EmailStr

    # Base de datos
    database_path: Path = Path("onboardings.db")

    # Logging
    log_level: str = "INFO"


settings = Settings()
