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


def register_admin_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        """Страница управления пользователями"""
        users = User.query.all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/users/create', methods=['GET', 'POST'])
    @admin_required
    def create_user():
        """Создание нового пользователя"""
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            full_name = request.form['full_name']
            role = request.form['role']

            # Проверяем, не существует ли уже такой пользователь
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                flash('Пользователь с таким логином уже существует', 'error')
                return render_template('admin/create_user.html')

            # Создаем нового пользователя
            user = User(
                username=username,
                full_name=full_name,
                role=role,
                created_by=session['user_id']
            )
            user.set_password(password)

            # Преобразуем текстовые поля в верхний регистр
            exclude_fields = {'password_hash', 'username'}  # username и пароль оставляем как есть
            uppercase_string_fields(user, exclude_fields)

            db.session.add(user)
            db.session.commit()

            log_user_action(f'Создан пользователь: {username}')
            flash(f'Пользователь {username} успешно создан', 'success')
            return redirect(url_for('admin_users'))

        return render_template('admin/create_user.html')

    @app.route('/admin/users/<int:user_id>/toggle')
    @admin_required
    def toggle_user_status(user_id):
        """Включение/отключение пользователя"""
        user = User.query.get_or_404(user_id)

        if user.id == session['user_id']:
            flash('Нельзя отключить самого себя', 'error')
            return redirect(url_for('admin_users'))

        user.is_active = not user.is_active
        db.session.commit()

        status = 'активирован' if user.is_active else 'деактивирован'
        log_user_action(f'Пользователь {user.username} {status}')
        flash(f'Пользователь {user.username} {status}', 'success')

        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def delete_user(user_id):
        """Удаление пользователя"""
        user = User.query.get_or_404(user_id)

        if user.id == session['user_id']:
            flash('Нельзя удалить самого себя', 'error')
            return redirect(url_for('admin_users'))

        username = user.username
        db.session.delete(user)
        db.session.commit()

        log_user_action(f'Удален пользователь: {username}')
        flash(f'Пользователь {username} удален', 'success')

        return redirect(url_for('admin_users'))

    @app.route('/admin/logs')
    @admin_required
    def admin_logs():
        """Страница просмотра логов"""
        page = request.args.get('page', 1, type=int)
        per_page = 50

        # Получаем логи с пагинацией
        logs = db.session.execute("""
            SELECT "ID_LOG", "LIST_ID", "USER_NAME", "DATE_IZM", "TIME_IZM"
            FROM "LOG" 
            ORDER BY "ID_LOG" DESC 
            LIMIT :limit OFFSET :offset
        """, {
            'limit': per_page,
            'offset': (page - 1) * per_page
        }).fetchall()

        # Общее количество записей
        total_count = db.session.execute('SELECT COUNT(*) FROM "LOG"').scalar()

        # Информация о пагинации
        has_prev = page > 1
        has_next = (page * per_page) < total_count
        prev_page = page - 1 if has_prev else None
        next_page = page + 1 if has_next else None

        return render_template('admin/logs.html', 
                             logs=logs, 
                             page=page,
                             has_prev=has_prev,
                             has_next=has_next,
                             prev_page=prev_page,
                             next_page=next_page,
                             total_count=total_count)

    @app.route('/admin/reports')
    @admin_required
    def admin_reports():
        """Главная страница отчетов"""
        # Получаем быструю статистику
        total_repatriants = db.session.execute('SELECT COUNT(*) FROM "MAIN"').scalar()
        total_users = db.session.execute('SELECT COUNT(*) FROM "USERS" WHERE "IS_ACTIVE" = TRUE').scalar()

        # Регистрации сегодня
        today = datetime.now().date()
        registrations_today = db.session.execute("""
            SELECT COUNT(*) FROM "LOG" 
            WHERE "DATE_IZM" = :today 
            AND "USER_NAME" LIKE '%Зарегистрирован репатриант%'
        """, {'today': today}).scalar()

        # Общее количество действий
        total_logs = db.session.execute('SELECT COUNT(*) FROM "LOG"').scalar()

        return render_template('admin/reports.html',
                             total_repatriants=total_repatriants,
                             total_users=total_users,
                             registrations_today=registrations_today,
                             total_logs=total_logs)

    @app.route('/admin/reports/social-adaptation')
    @admin_required
    def report_social_adaptation():
        """Отчет по данным социально адаптационного отдела"""
        # Статистика по записям
        total_housing = HousingRecord.query.count()
        total_social = SocialHelpRecord.query.count()
        total_events = EventRecord.query.count()
        total_other = OtherRecord.query.count()

        # Получаем все записи с информацией о репатриантах
        housing_records = db.session.query(HousingRecord, Repatriant).join(
            Repatriant, HousingRecord.repatriant_id == Repatriant.id
        ).order_by(HousingRecord.created_at.desc()).limit(100).all()

        social_records = db.session.query(SocialHelpRecord, Repatriant).join(
            Repatriant, SocialHelpRecord.repatriant_id == Repatriant.id
        ).order_by(SocialHelpRecord.created_at.desc()).limit(100).all()

        event_records = db.session.query(EventRecord, Repatriant).join(
            Repatriant, EventRecord.repatriant_id == Repatriant.id
        ).order_by(EventRecord.created_at.desc()).limit(100).all()

        other_records = db.session.query(OtherRecord, Repatriant).join(
            Repatriant, OtherRecord.repatriant_id == Repatriant.id
        ).order_by(OtherRecord.created_at.desc()).limit(100).all()

        # Статистика по типам помощи
        help_type_stats = db.session.execute("""
            SELECT 
                CASE 
                    WHEN "CUSTOM_HELP_TYPE" IS NOT NULL AND "CUSTOM_HELP_TYPE" != '' 
                    THEN "CUSTOM_HELP_TYPE"
                    ELSE "HELP_TYPE"
                END as help_type,
                COUNT(*) as count
            FROM "SOCIAL_HELP_RECORDS"
            GROUP BY help_type
            ORDER BY count DESC
        """).fetchall()

        # Статистика по типам мероприятий
        event_type_stats = db.session.execute("""
            SELECT "EVENT_TYPE", COUNT(*) as count
            FROM "EVENT_RECORDS"
            WHERE "EVENT_TYPE" IS NOT NULL AND "EVENT_TYPE" != ''
            GROUP BY "EVENT_TYPE"
            ORDER BY count DESC
        """).fetchall()

        return render_template('admin/report_social_adaptation.html',
                             total_housing=total_housing,
                             total_social=total_social,
                             total_events=total_events,
                             total_other=total_other,
                             housing_records=housing_records,
                             social_records=social_records,
                             event_records=event_records,
                             other_records=other_records,
                             help_type_stats=help_type_stats,
                             event_type_stats=event_type_stats)

    @app.route('/admin/reports/repatriants')
    @admin_required
    def report_repatriants():
        """Отчет по статистике репатриантов"""
        # Общая статистика
        total_count = db.session.execute('SELECT COUNT(*) FROM "MAIN"').scalar()

        # По полу
        sex_stats = db.session.execute("""
            SELECT "SEX", COUNT(*) as count
            FROM "MAIN"
            WHERE "SEX" IS NOT NULL
            GROUP BY "SEX"
            ORDER BY count DESC
        """).fetchall()

        # По странам прибытия
        country_stats = db.session.execute("""
            SELECT "FROM_LOC", COUNT(*) as count
            FROM "MAIN"
            WHERE "FROM_LOC" IS NOT NULL AND "FROM_LOC" != ''
            GROUP BY "FROM_LOC"
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()

        # По национальности
        nationality_stats = db.session.execute("""
            SELECT "REZERV", COUNT(*) as count
            FROM "MAIN"
            WHERE "REZERV" IS NOT NULL AND "REZERV" != ''
            GROUP BY "REZERV"
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()

        # По семейному положению
        family_status_stats = db.session.execute("""
            SELECT "SEM_POLOJ", COUNT(*) as count
            FROM "MAIN"
            WHERE "SEM_POLOJ" IS NOT NULL AND "SEM_POLOJ" != ''
            GROUP BY "SEM_POLOJ"
            ORDER BY count DESC
        """).fetchall()

        # Возрастные группы (примерно, по году рождения)
        age_groups = db.session.execute("""
            SELECT 
                CASE 
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM "DATE_R") < 18 THEN 'До 18 лет'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM "DATE_R") BETWEEN 18 AND 65 THEN '18-65 лет'
                    WHEN EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM "DATE_R") > 65 THEN 'Старше 65 лет'
                    ELSE 'Не указан возраст'
                END as age_group,
                COUNT(*) as count
            FROM "MAIN"
            WHERE "DATE_R" IS NOT NULL
            GROUP BY age_group
            ORDER BY count DESC
        """).fetchall()

        return render_template('admin/report_repatriants.html',
                             total_count=total_count,
                             sex_stats=sex_stats,
                             country_stats=country_stats,
                             nationality_stats=nationality_stats,
                             family_status_stats=family_status_stats,
                             age_groups=age_groups)

    @app.route('/admin/reports/user-activity')
    @admin_required
    def report_user_activity():
        """Отчет по активности пользователей"""
        # Активность пользователей по количеству действий
        user_activity = db.session.execute("""
            SELECT 
                SUBSTRING("USER_NAME" FROM 1 FOR POSITION(':' IN "USER_NAME") - 1) as username,
                COUNT(*) as action_count,
                MAX("DATE_IZM") as last_activity
            FROM "LOG"
            WHERE "USER_NAME" LIKE '%:%'
            GROUP BY username
            ORDER BY action_count DESC
        """).fetchall()

        # Последние входы пользователей
        last_logins = db.session.execute("""
            SELECT "USERNAME", "LAST_LOGIN", "FULL_NAME"
            FROM "USERS"
            WHERE "IS_ACTIVE" = TRUE
            ORDER BY "LAST_LOGIN" DESC NULLS LAST
        """).fetchall()

        # Активность по дням (последние 30 дней)
        daily_activity = db.session.execute("""
            SELECT "DATE_IZM", COUNT(*) as actions_count
            FROM "LOG"
            WHERE "DATE_IZM" >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY "DATE_IZM"
            ORDER BY "DATE_IZM" DESC
        """).fetchall()

        return render_template('admin/report_user_activity.html',
                             user_activity=user_activity,
                             last_logins=last_logins,
                             daily_activity=daily_activity)

    @app.route('/admin/reports/time-stats')
    @admin_required
    def report_time_stats():
        """Отчет по временной статистике"""
        # Регистрации по дням (последние 30 дней)
        daily_registrations = db.session.execute("""
            SELECT "DATE_IZM", COUNT(*) as registrations
            FROM "LOG"
            WHERE "DATE_IZM" >= CURRENT_DATE - INTERVAL '30 days'
            AND "USER_NAME" LIKE '%Зарегистрирован репатриант%'
            GROUP BY "DATE_IZM"
            ORDER BY "DATE_IZM" DESC
        """).fetchall()

        # Регистрации по месяцам (последние 12 месяцев)
        monthly_registrations = db.session.execute("""
            SELECT 
                EXTRACT(YEAR FROM "DATE_IZM") as year,
                EXTRACT(MONTH FROM "DATE_IZM") as month,
                COUNT(*) as registrations
            FROM "LOG"
            WHERE "DATE_IZM" >= CURRENT_DATE - INTERVAL '12 months'
            AND "USER_NAME" LIKE '%Зарегистрирован репатриант%'
            GROUP BY year, month
            ORDER BY year DESC, month DESC
        """).fetchall()

        # Активность по часам дня
        hourly_activity = db.session.execute("""
            SELECT 
                EXTRACT(HOUR FROM "TIME_IZM") as hour,
                COUNT(*) as actions_count
            FROM "LOG"
            WHERE "DATE_IZM" >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY hour
            ORDER BY hour
        """).fetchall()

        return render_template('admin/report_time_stats.html',
                             daily_registrations=daily_registrations,
                             monthly_registrations=monthly_registrations,
                             hourly_activity=hourly_activity)

    @app.route('/admin/reports/family-stats')
    @admin_required
    def report_family_stats():
        """Отчет по семейной статистике"""
        # Общее количество семей
        total_families = db.session.execute('SELECT COUNT(*) FROM "MAIN"').scalar()

        # Статистика по детям
        children_stats = db.session.execute("""
            SELECT 
                "LIST_ID",
                COUNT(*) as children_count
            FROM "CHILDREN"
            GROUP BY "LIST_ID"
            ORDER BY children_count DESC
        """).fetchall()

        # Статистика по взрослым членам семьи
        family_members_stats = db.session.execute("""
            SELECT 
                "LIST_ID",
                COUNT(*) as family_count
            FROM "FAMILY"
            GROUP BY "LIST_ID"
            ORDER BY family_count DESC
        """).fetchall()

        # Многодетные семьи (3+ детей)
        large_families = db.session.execute("""
            SELECT 
                "LIST_ID",
                COUNT(*) as children_count
            FROM "CHILDREN"
            GROUP BY "LIST_ID"
            HAVING COUNT(*) >= 3
            ORDER BY children_count DESC
        """).fetchall()

        # Одинокие репатрианты (без семьи)
        single_repatriants = db.session.execute("""
            SELECT COUNT(*)
            FROM "MAIN" m
            LEFT JOIN "CHILDREN" c ON m."ID" = c."LIST_ID"
            LEFT JOIN "FAMILY" f ON m."ID" = f."LIST_ID"
            WHERE c."LIST_ID" IS NULL AND f."LIST_ID" IS NULL
        """).scalar()

        return render_template('admin/report_family_stats.html',
                             total_families=total_families,
                             children_stats=children_stats,
                             family_members_stats=family_members_stats,
                             large_families=large_families,
                             single_repatriants=single_repatriants)

    @app.route('/admin/reports/system')
    @admin_required
    def report_system():
        """Системные отчеты"""
        # Общая статистика системы
        total_repatriants = db.session.execute('SELECT COUNT(*) FROM "MAIN"').scalar()
        total_users = db.session.execute('SELECT COUNT(*) FROM "USERS"').scalar()
        total_logs = db.session.execute('SELECT COUNT(*) FROM "LOG"').scalar()

        # Статистика по типам действий
        action_types = db.session.execute("""
            SELECT 
                CASE 
                    WHEN "USER_NAME" LIKE '%Зарегистрирован репатриант%' THEN 'Регистрации'
                    WHEN "USER_NAME" LIKE '%Отредактирован репатриант%' THEN 'Редактирования'
                    WHEN "USER_NAME" LIKE '%Удален репатриант%' THEN 'Удаления'
                    WHEN "USER_NAME" LIKE '%Вход в систему%' THEN 'Входы'
                    WHEN "USER_NAME" LIKE '%Выход из системы%' THEN 'Выходы'
                    ELSE 'Другие действия'
                END as action_type,
                COUNT(*) as count
            FROM "LOG"
            GROUP BY action_type
            ORDER BY count DESC
        """).fetchall()

        # Активность по дням недели
        weekday_activity = db.session.execute("""
            SELECT 
                EXTRACT(DOW FROM "DATE_IZM") as day_of_week,
                COUNT(*) as actions_count
            FROM "LOG"
            WHERE "DATE_IZM" >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY day_of_week
            ORDER BY day_of_week
        """).fetchall()

        # Топ пользователей по активности
        top_users = db.session.execute("""
            SELECT 
                SUBSTRING("USER_NAME" FROM 1 FOR POSITION(':' IN "USER_NAME") - 1) as username,
                COUNT(*) as action_count
            FROM "LOG"
            WHERE "USER_NAME" LIKE '%:%'
            GROUP BY username
            ORDER BY action_count DESC
            LIMIT 10
        """).fetchall()

        return render_template('admin/report_system.html',
                             total_repatriants=total_repatriants,
                             total_users=total_users,
                             total_logs=total_logs,
                             action_types=action_types,
                             weekday_activity=weekday_activity,
                             top_users=top_users)

    @app.route('/admin/reports/export')
    @admin_required
    def report_export():
        """Страница экспорта данных"""
        return render_template('admin/report_export.html')

    @app.route('/admin/export/repatriants/<format>')
    @admin_required
    def export_repatriants(format):
        """Экспорт данных репатриантов"""
        from flask import make_response
        import csv
        import io

        # Получаем данные репатриантов
        repatriants = db.session.execute("""
            SELECT "ID", "F", "I", "O", "SEX", "DATE_R", "FROM_LOC", "SEM_POLOJ", "REZERV"
            FROM "MAIN"
            ORDER BY "ID"
        """).fetchall()

        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)

            # Заголовки
            writer.writerow(['ID', 'Фамилия', 'Имя', 'Отчество', 'Пол', 'Дата рождения', 'Страна прибытия', 'Семейное положение', 'Национальность'])

            # Данные
            for row in repatriants:
                writer.writerow([row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8]])

            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=repatriants_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response

        elif format == 'json':
            import json
            data = []
            for row in repatriants:
                data.append({
                    'id': row[0],
                    'surname': row[1],
                    'name': row[2],
                    'patronymic': row[3],
                    'sex': row[4],
                    'birth_date': row[5].isoformat() if row[5] else None,
                    'from_country': row[6],
                    'family_status': row[7],
                    'nationality': row[8]
                })

            response = make_response(json.dumps(data, ensure_ascii=False, indent=2))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=repatriants_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            return response

        else:
            flash('Неподдерживаемый формат экспорта', 'error')
            return redirect(url_for('report_export'))

    @app.route('/admin/export/logs/<format>')
    @admin_required
    def export_logs(format):
        """Экспорт логов системы"""
        from flask import make_response
        import csv
        import io

        # Получаем логи
        logs = db.session.execute("""
            SELECT "ID_LOG", "LIST_ID", "USER_NAME", "DATE_IZM", "TIME_IZM"
            FROM "LOG"
            ORDER BY "ID_LOG" DESC
        """).fetchall()

        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)

            # Заголовки
            writer.writerow(['ID', 'ID репатрианта', 'Пользователь', 'Дата', 'Время'])

            # Данные
            for row in logs:
                writer.writerow([row[0], row[1], row[2], row[3], row[4]])

            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response

        elif format == 'json':
            import json
            data = []
            for row in logs:
                data.append({
                    'id': row[0],
                    'repatriant_id': row[1],
                    'user_name': row[2],
                    'date': row[3].isoformat() if row[3] else None,
                    'time': row[4].isoformat() if row[4] else None
                })

            response = make_response(json.dumps(data, ensure_ascii=False, indent=2))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            return response

        else:
            flash('Неподдерживаемый формат экспорта', 'error')
            return redirect(url_for('report_export'))

    @app.route('/admin/export/users/<format>')
    @admin_required
    def export_users(format):
        """Экспорт пользователей"""
        from flask import make_response
        import csv
        import io

        # Получаем пользователей
        users = db.session.execute("""
            SELECT "ID", "USERNAME", "FULL_NAME", "ROLE", "IS_ACTIVE", "CREATED_AT", "LAST_LOGIN"
            FROM "USERS"
            ORDER BY "ID"
        """).fetchall()

        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)

            # Заголовки
            writer.writerow(['ID', 'Логин', 'Полное имя', 'Роль', 'Активен', 'Дата создания', 'Последний вход'])

            # Данные
            for row in users:
                writer.writerow([row[0], row[1], row[2], row[3], 'Да' if row[4] else 'Нет', row[5], row[6]])

            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response

        elif format == 'json':
            import json
            data = []
            for row in users:
                data.append({
                    'id': row[0],
                    'username': row[1],
                    'full_name': row[2],
                    'role': row[3],
                    'is_active': bool(row[4]),
                    'created_at': row[5].isoformat() if row[5] else None,
                    'last_login': row[6].isoformat() if row[6] else None
                })

            response = make_response(json.dumps(data, ensure_ascii=False, indent=2))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            return response

        else:
            flash('Неподдерживаемый формат экспорта', 'error')
            return redirect(url_for('report_export'))

    @app.route('/admin/export/families/<format>')
    @admin_required
    def export_families(format):
        """Экспорт семейных данных"""
        from flask import make_response
        import csv
        import io

        # Получаем детей
        children = db.session.execute("""
            SELECT "LIST_ID", "STEP_ROD", "F", "I", "O", "GOD_R", "GRAJDANSTVO", "NACIONALNOST"
            FROM "CHILDREN"
            ORDER BY "LIST_ID", "ID"
        """).fetchall()

        # Получаем взрослых членов семьи
        family_members = db.session.execute("""
            SELECT "LIST_ID", "STEP_ROD", "F", "I", "O", "GOD_R", "GRAJDANSTVO", "NACIONALNOST"
            FROM "FAMILY"
            ORDER BY "LIST_ID", "ID"
        """).fetchall()

        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)

            # Заголовки
            writer.writerow(['ID репатрианта', 'Тип', 'Степень родства', 'Фамилия', 'Имя', 'Отчество', 'Год рождения', 'Гражданство', 'Национальность'])

            # Данные детей
            for row in children:
                writer.writerow([row[0], 'Ребенок', row[1], row[2], row[3], row[4], row[5], row[6], row[7]])

            # Данные взрослых
            for row in family_members:
                writer.writerow([row[0], 'Взрослый', row[1], row[2], row[3], row[4], row[5], row[6], row[7]])

            output.seek(0)
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=families_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return response

        elif format == 'json':
            import json
            data = {
                'children': [],
                'family_members': []
            }

            # Данные детей
            for row in children:
                data['children'].append({
                    'repatriant_id': row[0],
                    'relationship': row[1],
                    'surname': row[2],
                    'name': row[3],
                    'patronymic': row[4],
                    'birth_year': row[5],
                    'citizenship': row[6],
                    'nationality': row[7]
                })

            # Данные взрослых
            for row in family_members:
                data['family_members'].append({
                    'repatriant_id': row[0],
                    'relationship': row[1],
                    'surname': row[2],
                    'name': row[3],
                    'patronymic': row[4],
                    'birth_year': row[5],
                    'citizenship': row[6],
                    'nationality': row[7]
                })

            response = make_response(json.dumps(data, ensure_ascii=False, indent=2))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=families_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            return response

        else:
            flash('Неподдерживаемый формат экспорта', 'error')
            return redirect(url_for('report_export'))

