from __future__ import annotations

from flask import Flask

from .config import Config
from .extensions import db
from .services.storage import create_disk_folders
from .utils.status import check_repatriant_status


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    # Импортируем модели, чтобы зарегистрировались слушатели событий SQLAlchemy
    from . import models as _models  # noqa: F401

    # Создаем папки для хранения/временных файлов
    create_disk_folders(app)

    # Регистрируем маршруты
    from .routes.admin import register_admin_routes
    from .routes.api_housing import register_api_housing_routes
    from .routes.api_social import register_api_social_routes
    from .routes.auth import register_auth_routes
    from .routes.main import register_main_routes
    from .routes.repatriants import register_repatriant_routes

    register_main_routes(app)
    register_api_social_routes(app)
    register_api_housing_routes(app)
    register_repatriant_routes(app)
    register_auth_routes(app)
    register_admin_routes(app)

    # Добавляем функцию в контекст шаблонов
    @app.context_processor
    def utility_processor():
        return dict(check_repatriant_status=check_repatriant_status)

    return app
