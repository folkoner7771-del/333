from __future__ import annotations

from datetime import datetime, timedelta


def check_repatriant_status(rep_status_date):
    """Проверяет статус репатрианта и возвращает информацию о его состоянии"""

    if not rep_status_date:
        return {
            "status": "not_set",
            "color": "gray",
            "text": "Не указан",
            "is_expired": False,
            "days_left": None,
        }

    # Вычисляем дату истечения (5 лет с даты получения статуса)
    expiration_date = rep_status_date + timedelta(days=5 * 365)  # 5 лет
    today = datetime.now().date()

    if today > expiration_date:
        # Статус истек
        days_expired = (today - expiration_date).days
        return {
            "status": "expired",
            "color": "red",
            "text": f"Истек ({days_expired} дн. назад)",
            "is_expired": True,
            "days_left": -days_expired,
        }

    # Статус действует
    days_left = (expiration_date - today).days
    return {
        "status": "active",
        "color": "green",
        "text": f"Действует ({days_left} дн.)",
        "is_expired": False,
        "days_left": days_left,
    }
