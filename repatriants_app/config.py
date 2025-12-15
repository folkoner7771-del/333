from __future__ import annotations

import os


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-here")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql://postgres:123@localhost/postgres"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Конфигурация для равномерного заполнения дисков
    STORAGE_DISKS = [
        {"path": "D:\\repatriants_files", "priority": 1, "name": "Диск D"},
        {"path": "E:\\repatriants_files", "priority": 2, "name": "Диск E"},
    ]
    BACKUP_DISK = "F:\\repatriants_backup"  # Резервный диск

    # Старая папка для совместимости (временные файлы)
    UPLOAD_FOLDER = "uploads"
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB для сканов документов
