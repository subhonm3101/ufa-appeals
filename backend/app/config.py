from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Порт 5433: см. docker-compose.yml. Можно переопределить переменной окружения
    # APPEALS_DATABASE_URL или файлом backend/.env
    database_url: str = "postgresql+psycopg2://appeals:appeals@127.0.0.1:5433/appeals"

    model_config = SettingsConfigDict(env_prefix="APPEALS_", env_file=".env", extra="ignore")


settings = Settings()
