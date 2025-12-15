from __future__ import annotations

import os
import shutil
import uuid

from flask import current_app
from werkzeug.utils import secure_filename


def create_disk_folders(app) -> None:
    """Создает необходимые папки на дисках"""

    folders_to_create = [
        app.config["BACKUP_DISK"],  # Резервный диск
        os.path.join(app.config["UPLOAD_FOLDER"], "temp"),  # Временные файлы
        os.path.join(app.config["UPLOAD_FOLDER"], "documents"),  # Для совместимости
        os.path.join(app.config["UPLOAD_FOLDER"], "avatars"),  # Для совместимости
    ]

    # Добавляем папки для каждого диска хранения
    for disk in app.config["STORAGE_DISKS"]:
        folders_to_create.append(disk["path"])

    for folder in folders_to_create:
        try:
            os.makedirs(folder, exist_ok=True)
            print(f"✓ Папка создана/проверена: {folder}")
        except Exception as e:
            print(f"✗ Ошибка создания папки {folder}: {e}")


def get_best_disk(app=None) -> str:
    """Выбирает диск с наименьшим заполнением"""

    if app is None:
        app = current_app

    best_disk = None
    max_free_space = 0

    for disk in app.config["STORAGE_DISKS"]:
        try:
            total, used, free = shutil.disk_usage(disk["path"])
            free_gb = free // (1024**3)

            print(f"{disk['name']}: {free_gb} ГБ свободно")

            if free_gb > max_free_space:
                max_free_space = free_gb
                best_disk = disk

        except Exception as e:
            print(f"Ошибка проверки диска {disk['name']}: {e}")
            continue

    if best_disk:
        print(f"Выбран диск: {best_disk['name']} ({max_free_space} ГБ свободно)")
        return best_disk["path"]

    print("Все диски недоступны, используем первый диск")
    return app.config["STORAGE_DISKS"][0]["path"]


ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif"}


def allowed_file(filename: str) -> bool:
    """Проверяет разрешенные расширения файлов"""

    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_file(file, folder: str, prefix: str = "") -> str | None:
    """Сохраняет загруженный файл и возвращает путь к нему"""

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"

        print(f"Сохраняем файл: {unique_filename} в папку: {folder}")

        app = current_app

        if folder in ["documents", "avatars"]:
            best_disk_path = get_best_disk(app)
            upload_path = best_disk_path
            relative_path = f"{folder}/{unique_filename}"
            print(f"Выбран диск: {best_disk_path}")
        else:
            upload_path = os.path.join(app.config["UPLOAD_FOLDER"], folder)
            relative_path = os.path.join(folder, unique_filename)
            print(f"Используем старую папку: {upload_path}")

        os.makedirs(upload_path, exist_ok=True)
        print(f"Папка создана/проверена: {upload_path}")

        file_path = os.path.join(upload_path, unique_filename)
        print(f"Сохраняем файл по пути: {file_path}")
        file.save(file_path)

        if os.path.exists(file_path):
            print(f"✓ Файл успешно сохранен: {file_path}")
        else:
            print(f"✗ ОШИБКА: Файл не найден после сохранения: {file_path}")

        result_path = relative_path.replace("\\", "/")
        print(f"Возвращаем путь: {result_path}")
        return result_path

    return None


def delete_file(file_path: str | None) -> bool:
    """Удаляет файл с диска"""

    if not file_path:
        return False

    app = current_app

    if file_path.startswith("documents/") or file_path.startswith("avatars/"):
        filename = file_path.split("/")[1]

        for disk in app.config["STORAGE_DISKS"]:
            full_path = os.path.join(disk["path"], filename)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                    print(f"Файл удален с {disk['name']}: {filename}")
                    return True
                except OSError as e:
                    print(f"Ошибка удаления файла с {disk['name']}: {e}")
                    continue
        return False

    normalized_path = file_path.replace("/", "\\")
    full_path = os.path.join(app.config["UPLOAD_FOLDER"], normalized_path)
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            return True
        except OSError:
            return False

    return False
