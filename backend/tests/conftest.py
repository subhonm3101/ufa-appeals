import os

# Интеграционные тесты идут в базу из APPEALS_TEST_DATABASE_URL (если задана).
# Переменная выставляется ДО импорта приложения, чтобы engine смотрел в нужную базу.
_test_url = os.environ.get("APPEALS_TEST_DATABASE_URL")
if _test_url:
    os.environ["APPEALS_DATABASE_URL"] = _test_url
