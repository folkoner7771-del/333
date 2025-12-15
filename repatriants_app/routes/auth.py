from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timedelta

from flask import (
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import text

from ..extensions import db
from ..models import (
    Child,
    EventRecord,
    FamilyMember,
    HousingDepartmentRecord,
    HousingQueue,
    HousingRecord,
    OtherRecord,
    Repatriant,
    SocialHelpRecord,
    User,
)
from ..services.audit import log_user_action
from ..services.storage import allowed_file, delete_file, get_best_disk, save_file
from ..utils.auth import admin_required, login_required
from ..utils.status import check_repatriant_status
from ..utils.text import normalize_nationality_value, uppercase_string_fields


def register_auth_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    # Маршруты авторизации
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Страница входа"""
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']

            user = User.query.filter_by(username=username, is_active=True).first()

            if user and user.check_password(password):
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                session['last_activity'] = datetime.now().isoformat()

                # Обновляем время последнего входа
                user.last_login = datetime.now()
                db.session.commit()

                log_user_action('Вход в систему')

                flash(f'Добро пожаловать, {user.full_name}!', 'success')
                return redirect(url_for('register'))
            else:
                flash('Неверный логин или пароль', 'error')

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        """Выход из системы"""
        if 'user_id' in session:
            log_user_action('Выход из системы')

        session.clear()
        flash('Вы вышли из системы', 'info')
        return redirect(url_for('login'))

