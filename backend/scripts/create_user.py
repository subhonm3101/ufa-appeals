"""Создание пользователя из командной строки (первый администратор и т.п.).

Запуск из корня проекта:
    python backend/scripts/create_user.py --email admin@example.com --name "Имя Фамилия" --role admin
Пароль запрашивается скрытым вводом: в истории команд и в списке процессов он не появляется.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # папка backend

from sqlalchemy import text  # noqa: E402

from app.auth import ROLES  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.audit import log_event  # noqa: E402
from app.services.security import check_password_strength, hash_password, normalize_email  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--email", required=True)
ap.add_argument("--name", default=None)
ap.add_argument("--role", required=True, choices=ROLES)
args = ap.parse_args()

try:
    email = normalize_email(args.email)
except ValueError as exc:
    sys.exit(str(exc))

password = getpass.getpass("Пароль: ")
if password != getpass.getpass("Повторите пароль: "):
    sys.exit("Пароли не совпадают")
error = check_password_strength(password, email)
if error:
    sys.exit(error)

with SessionLocal() as session:
    if session.execute(text("SELECT 1 FROM users WHERE lower(email) = :e"), {"e": email}).first():
        sys.exit("Пользователь с таким email уже существует")
    uid = session.execute(
        text("INSERT INTO users (email, password_hash, full_name, role) VALUES (:e, :h, :n, :r) RETURNING id"),
        {"e": email, "h": hash_password(password), "n": args.name, "r": args.role},
    ).scalar_one()
    log_event(session, None, "user_created", "user", uid, details={"email": email, "role": args.role, "via": "cli"})
print(f"Создан пользователь {email} (id {uid}, роль {args.role})")
