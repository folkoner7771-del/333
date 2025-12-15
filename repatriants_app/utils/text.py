from __future__ import annotations


def normalize_nationality_value(value: str | None) -> str | None:
    """Нормализует значение национальности (преобразует женский род в мужской).

    Согласно стандартизации из normalize_nationality.py
    """

    if not value:
        return value

    value_upper = value.strip().upper()

    # Маппинг женского рода на мужской (стандартизированные значения)
    nationality_mapping = {
        "АБХАЗКА": "АБХАЗ",
        "АБАЗИНКА": "АБАЗИН",
        "КАБАРДИНКА": "КАБАРДИНЕЦ",
        "АДЫГЕЙКА": "АДЫГ",
        "УБЫХКА": "УБЫХ",
    }

    # Если значение есть в маппинге, возвращаем стандартизированное
    if value_upper in nationality_mapping:
        return nationality_mapping[value_upper]

    # Если значение уже стандартизировано, возвращаем как есть
    standard_values = ["АБХАЗ", "АБАЗИН", "КАБАРДИНЕЦ", "АДЫГ", "УБЫХ"]
    if value_upper in standard_values:
        return value_upper

    # Для всех остальных значений (включая "Другое") возвращаем как есть
    return value.strip()


def uppercase_string_fields(target, exclude_fields=None) -> None:
    """Преобразует все строковые поля модели в верхний регистр."""

    if exclude_fields is None:
        # Исключаем только технические поля: пароли, бинарные данные, пути к файлам
        exclude_fields = {
            "password_hash",
            "avatar_path",
            "documents_path",
            "file",
            "photo",
            "file_jil",
            "f_name",
            "f_name_jil",
        }

    # Преобразуем exclude_fields в нижний регистр для сравнения
    exclude_fields_lower = {field.lower() for field in exclude_fields}

    # Проходим по всем столбцам таблицы
    try:
        for column in target.__table__.columns:
            column_name = column.name.lower()

            # Пропускаем исключенные поля
            if column_name in exclude_fields_lower:
                continue

            # Получаем имя атрибута (может отличаться от имени столбца)
            attr_name = column.name

            # Проверяем, что атрибут существует в объекте
            if not hasattr(target, attr_name):
                continue

            # Получаем значение
            try:
                value = getattr(target, attr_name)

                # Если значение - строка и не пустое, преобразуем в верхний регистр
                if value is not None and isinstance(value, str) and value.strip():
                    setattr(target, attr_name, value.upper())
            except (AttributeError, TypeError, ValueError):
                continue
    except Exception:
        # Резервный подход: __dict__
        if hasattr(target, "__dict__"):
            for attr_name, value in target.__dict__.items():
                if attr_name.startswith("_") or attr_name.lower() in exclude_fields_lower:
                    continue
                if value is not None and isinstance(value, str) and value.strip():
                    try:
                        setattr(target, attr_name, value.upper())
                    except (AttributeError, TypeError, ValueError):
                        continue
