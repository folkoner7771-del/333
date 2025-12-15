from __future__ import annotations

from datetime import datetime, timedelta
from functools import wraps

from flask import flash, redirect, session, url_for

from ..models import User


def login_required(f):
    """Декоратор для проверки авторизации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        # Проверяем, не истекла ли сессия (24 часа)
        if "last_activity" in session:
            last_activity = datetime.fromisoformat(session["last_activity"])
            if datetime.now() - last_activity > timedelta(hours=24):
                session.clear()
                flash("Сессия истекла. Пожалуйста, войдите снова.", "warning")
                return redirect(url_for("login"))

        # Обновляем время последней активности
        session["last_activity"] = datetime.now().isoformat()
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Декоратор для проверки прав администратора"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        user = User.query.get(session["user_id"])
        if not user or user.role != "ADMIN":
            flash("Недостаточно прав для доступа к этой странице.", "error")
            return redirect(url_for("dashboard"))

        return f(*args, **kwargs)

    return decorated_function
