"""Настройки приложения: окружение и файл .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigError


class Settings(BaseSettings):
    """Все параметры читаются из переменных окружения или .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # GigaChat
    gigachat_credentials: str | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2"
    gigachat_verify_ssl_certs: bool = True

    # restful-booker
    booker_base_url: str = "https://restful-booker.herokuapp.com"
    booker_username: str = "admin"
    booker_password: str = "password123"
    booker_timeout: float = 15.0
    booker_max_retries: int = 2

    # агент
    agent_max_steps: int = 6
    agent_temperature: float = 0.0
    agent_llm_timeout: float = 60.0
    agent_verbose: bool = False

    @property
    def has_gigachat_credentials(self) -> bool:
        return bool(self.gigachat_credentials)

    def require_gigachat_credentials(self) -> str:
        if not self.gigachat_credentials:
            raise ConfigError(
                "Не задан GIGACHAT_CREDENTIALS. "
                "Скопируйте .env.example в .env и укажите ключ авторизации GigaChat."
            )
        return self.gigachat_credentials


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
