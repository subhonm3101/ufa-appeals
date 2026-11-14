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

    # Режим работы: в production сервер не запускается с ключом по умолчанию
    environment: str = "development"
    # Адреса сайта, которым разрешены запросы из браузера (через запятую)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Адреса обратных прокси (через запятую), которым доверяем X-Forwarded-For
    trusted_proxies: str = ""

    model_config = SettingsConfigDict(env_prefix="APPEALS_", env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]


settings = Settings()


def production_problems(s: "Settings") -> list[str]:
    """Что мешает запуску в режиме production (пустой список, если всё в порядке)."""
    if not s.is_production:
        return []
    problems = []
    if s.secret_key == DEFAULT_SECRET_KEY or len(s.secret_key) < 32:
        problems.append("APPEALS_SECRET_KEY: задайте случайный ключ длиной не менее 32 символов")
    if any(o.startswith("http://localhost") or o.startswith("http://127.") for o in s.cors_origin_list):
        problems.append("APPEALS_CORS_ORIGINS: уберите адреса localhost и укажите адрес сайта")
    return problems
