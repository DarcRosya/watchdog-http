from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, PostgresDsn

ENV_FILE_PATH = Path(__file__).resolve().parent.parent


class DatabaseSettings(BaseSettings):
    """Stores all environment variables related to connecting to the database."""
    USER: str = "postgres"
    PASS: SecretStr
    HOST: str = "localhost"
    PORT: int = 5432
    NAME: str = "watchdog-http"

    @property
    def DATABASE_URL(self) -> str:
        return str(PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.USER,
            password=self.PASS.get_secret_value(),
            host=self.HOST,
            port=self.PORT,
            path=self.NAME
        ))


class Settings(BaseSettings):
    """
    The main class aggregator, which is the sole source of configuration for the entire application.
    Pydantic automatically loads and validates settings at startup.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_nested_delimeter="__",
    )

    debug_mode: bool = False

    db: DatabaseSettings


settings = Settings()
