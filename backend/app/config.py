from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Settings(BaseSettings):
    # Порт 5433: см. docker-compose.yml. Можно переопределить переменной окружения
    # APPEALS_DATABASE_URL или файлом .env
    database_url: str = "postgresql+psycopg2://appeals:appeals@127.0.0.1:5433/appeals"

    # Ключ подписи токенов. Для реального использования задайте свой длинный случайный ключ
    # (переменная APPEALS_SECRET_KEY или файл .env); с ключом по умолчанию токены может подделать любой.
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_minutes: int = 480  # время жизни токена: 8 часов

    # Защита от подбора пароля: после стольких неудачных входов подряд вход блокируется на время окна
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    model_config = SettingsConfigDict(env_prefix="APPEALS_", env_file=".env", extra="ignore")


settings = Settings()
