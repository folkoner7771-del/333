from __future__ import annotations

from datetime import datetime

from flask import session
from sqlalchemy import text

from ..extensions import db
from ..models import User


def log_user_action(action, repatriant_id=None) -> None:
    """Логирует действие пользователя"""

    if "user_id" in session:
        user = User.query.get(session["user_id"])
        username = user.username if user else "Unknown"

        action_upper = action.upper() if action else ""

        # Получаем следующий ID_LOG
        max_log_id = db.session.execute(text('SELECT MAX("ID_LOG") FROM "LOG"')).scalar()
        next_log_id = (max_log_id or 0) + 1

        db.session.execute(
            text(
                """
                INSERT INTO "LOG" ("ID_LOG", "LIST_ID", "USER_NAME", "DATE_IZM", "TIME_IZM")
                VALUES (:id_log, :list_id, :username, :date_izm, :time_izm)
                """
            ),
            {
                "id_log": next_log_id,
                "list_id": repatriant_id,
                "username": f"{username}: {action_upper}",
                "date_izm": datetime.now().date(),
                "time_izm": datetime.now().time(),
            },
        )

        db.session.commit()
