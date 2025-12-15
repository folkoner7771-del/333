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


def register_api_social_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    # API endpoints для социально адаптационного отдела

    @app.route('/api/housing/<int:repatriant_id>', methods=['GET', 'POST'])
    @login_required
    def api_housing(repatriant_id):
        """API для работы с записями об аренде жилья"""
        if request.method == 'GET':
            # Для администратора показываем все записи (включая удаленные), для соц. адаптационного отдела только не удаленные
            user_role = session.get('role')

            if user_role == 'ADMIN':
                # Администратор видит все записи (включая удаленные)
                try:
                    # Пытаемся использовать обычный запрос с полем is_deleted
                    records = HousingRecord.query.filter_by(repatriant_id=repatriant_id).order_by(HousingRecord.created_at.desc()).all()
                except Exception as e:
                    # Если поле is_deleted не существует, используем прямой SQL запрос
                    print(f"Поле is_deleted не существует, используем прямой SQL: {e}")
                    try:
                        result = db.session.execute(text('''
                            SELECT "ID", "REPATRIANT_ID", "CONTRACT_NUMBER", "ADDRESS", "START_DATE", "END_DATE", 
                                   "COST", "DOCUMENTS_PATH", "NOTES", "CREATED_AT", "CREATED_BY"
                            FROM "HOUSING_RECORDS"
                            WHERE "REPATRIANT_ID" = :repatriant_id
                            ORDER BY "CREATED_AT" DESC
                        '''), {'repatriant_id': repatriant_id})

                        # Создаем словари вместо объектов модели
                        records_dict = []
                        for row in result:
                            records_dict.append({
                                'id': row[0],
                                'contract_number': row[1],
                                'address': row[2],
                                'start_date': row[3].strftime('%Y-%m-%d') if row[3] else None,
                                'end_date': row[4].strftime('%Y-%m-%d') if row[4] else None,
                                'cost': float(row[5]) if row[5] else None,
                                'documents': json.loads(row[6]) if row[6] else [],
                                'notes': row[7],
                                'created_at': row[8].strftime('%Y-%m-%d %H:%M:%S') if row[8] else None,
                                'is_deleted': False,  # По умолчанию False, так как поле не существует
                                'deleted_at': None
                            })
                        return jsonify(records_dict)
                    except Exception as sql_e:
                        print(f"Ошибка при выполнении SQL запроса: {sql_e}")
                        return jsonify([])
            else:
                # Для соц. адаптационного отдела показываем только не удаленные
                try:
                    # Проверяем, существует ли поле is_deleted
                    records = HousingRecord.query.filter_by(repatriant_id=repatriant_id, is_deleted=False).order_by(HousingRecord.created_at.desc()).all()
                except Exception as e:
                    # Если поле не существует, показываем все записи
                    print(f"Поле is_deleted не существует, показываем все записи: {e}")
                    records = HousingRecord.query.filter_by(repatriant_id=repatriant_id).order_by(HousingRecord.created_at.desc()).all()

            return jsonify([record.to_dict() for record in records])

        elif request.method == 'POST':
            try:
                form_data = request.form
                files = request.files.getlist('documents')

                # Проверяем обязательные поля
                if not form_data.get('address'):
                    return jsonify({'success': False, 'error': 'Адрес аренды обязателен для заполнения'}), 400
                if not form_data.get('start_date'):
                    return jsonify({'success': False, 'error': 'Дата заключения договора обязательна для заполнения'}), 400

                # Обрабатываем даты
                try:
                    start_date = datetime.strptime(form_data.get('start_date'), '%Y-%m-%d').date()
                except ValueError:
                    return jsonify({'success': False, 'error': 'Неверный формат даты заключения договора'}), 400

                end_date = None
                if form_data.get('end_date'):
                    try:
                        end_date = datetime.strptime(form_data.get('end_date'), '%Y-%m-%d').date()
                    except ValueError:
                        return jsonify({'success': False, 'error': 'Неверный формат даты расторжения договора'}), 400

                # Сохраняем файлы
                document_paths = []
                if files:
                    for file in files:
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                saved_path = save_file(file, 'documents', f'housing_{repatriant_id}_{uuid.uuid4().hex[:8]}')
                                if saved_path:
                                    document_paths.append(saved_path)

                # Обрабатываем стоимость
                cost = None
                if form_data.get('cost'):
                    try:
                        cost = float(form_data.get('cost'))
                    except ValueError:
                        cost = None

                # Создаем запись
                record = HousingRecord(
                    repatriant_id=repatriant_id,
                    contract_number=form_data.get('contract_number'),
                    address=form_data.get('address'),
                    start_date=start_date,
                    end_date=end_date,
                    cost=cost,
                    documents_path=json.dumps(document_paths) if document_paths else None,
                    notes=form_data.get('notes'),
                    created_by=session.get('user_id')
                )

                db.session.add(record)
                db.session.commit()

                log_user_action(f'Добавлена запись об аренде жилья для репатрианта {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 201

            except Exception as e:
                db.session.rollback()
                import traceback
                error_details = traceback.format_exc()
                print(f"Ошибка при сохранении записи об аренде: {error_details}")
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/housing/<int:record_id>', methods=['PUT', 'DELETE'])
    @login_required
    def api_update_housing(record_id):
        """Обновление или удаление записи об аренде жилья"""
        if request.method == 'PUT':
            try:
                record = HousingRecord.query.get_or_404(record_id)
                form_data = request.form
                files = request.files.getlist('documents')

                # Обновляем данные
                if form_data.get('contract_number'):
                    record.contract_number = form_data.get('contract_number')
                if form_data.get('address'):
                    record.address = form_data.get('address')
                if form_data.get('start_date'):
                    record.start_date = datetime.strptime(form_data.get('start_date'), '%Y-%m-%d').date()
                if form_data.get('end_date'):
                    record.end_date = datetime.strptime(form_data.get('end_date'), '%Y-%m-%d').date() if form_data.get('end_date') else None
                if form_data.get('cost'):
                    record.cost = float(form_data.get('cost')) if form_data.get('cost') else None
                if form_data.get('notes') is not None:
                    record.notes = form_data.get('notes')

                # Обрабатываем новые файлы
                if files:
                    existing_docs = json.loads(record.documents_path) if record.documents_path else []
                    for file in files:
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                saved_path = save_file(file, 'documents', f'housing_{record.repatriant_id}_{uuid.uuid4().hex[:8]}')
                                if saved_path:
                                    existing_docs.append(saved_path)
                    record.documents_path = json.dumps(existing_docs) if existing_docs else None

                db.session.commit()

                log_user_action(f'Обновлена запись об аренде жилья {record_id}', record.repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 200

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

        elif request.method == 'DELETE':
            try:
                record = HousingRecord.query.get_or_404(record_id)
                repatriant_id = record.repatriant_id
                user_role = session.get('role')

                # ВСЕГДА используем мягкое удаление (soft delete) - помечаем как удаленное
                # Администратор видит все записи (включая удаленные)
                # Пользователь соц. адаптационного отдела видит только не удаленные
                try:
                    # Проверяем, существует ли поле в БД
                    db.session.execute(text('SELECT "IS_DELETED" FROM "HOUSING_RECORDS" WHERE "ID" = :id LIMIT 1'), {'id': record_id})
                    # Если запрос прошел, поле существует - делаем мягкое удаление
                    record.is_deleted = True
                    record.deleted_at = datetime.utcnow()
                    record.deleted_by = session.get('user_id')
                    log_user_action(f'Помечена как удаленная запись об аренде жилья {record_id} (пользователь: {user_role})', repatriant_id)
                except Exception as e:
                    # Если поля не существуют, возвращаем ошибку с сообщением
                    return jsonify({
                        'success': False, 
                        'error': 'Поля для мягкого удаления не добавлены в БД. Запустите миграцию: python scripts/add_soft_delete_fields.py'
                    }), 400

                db.session.commit()
                return jsonify({'success': True}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/social/<int:repatriant_id>', methods=['GET', 'POST'])
    @login_required
    def api_social(repatriant_id):
        """API для работы с записями о социальной помощи"""
        if request.method == 'GET':
            # Для администратора показываем все записи (включая удаленные), для соц. адаптационного отдела только не удаленные
            user_role = session.get('role')

            if user_role == 'ADMIN':
                # Администратор видит все записи (включая удаленные)
                try:
                    # Пытаемся использовать обычный запрос с полем is_deleted
                    records = SocialHelpRecord.query.filter_by(repatriant_id=repatriant_id).order_by(SocialHelpRecord.created_at.desc()).all()
                except Exception as e:
                    # Если поле is_deleted не существует, используем прямой SQL запрос
                    print(f"Поле is_deleted не существует, используем прямой SQL: {e}")
                    try:
                        result = db.session.execute(text('''
                            SELECT "ID", "REPATRIANT_ID", "HELP_TYPE", "CUSTOM_HELP_TYPE", "RESPONSIBLE", 
                                   "AMOUNT", "DOCUMENTS_PATH", "NOTES", "CREATED_AT", "CREATED_BY"
                            FROM "SOCIAL_HELP_RECORDS"
                            WHERE "REPATRIANT_ID" = :repatriant_id
                            ORDER BY "CREATED_AT" DESC
                        '''), {'repatriant_id': repatriant_id})

                        # Создаем словари вместо объектов модели
                        records_dict = []
                        for row in result:
                            records_dict.append({
                                'id': row[0],
                                'help_type': row[2],
                                'custom_help_type': row[3],
                                'responsible': row[4],
                                'amount': float(row[5]) if row[5] else None,
                                'documents': json.loads(row[6]) if row[6] else [],
                                'notes': row[7],
                                'created_at': row[8].strftime('%Y-%m-%d %H:%M:%S') if row[8] else None,
                                'is_deleted': False,  # По умолчанию False, так как поле не существует
                                'deleted_at': None
                            })
                        return jsonify(records_dict)
                    except Exception as sql_e:
                        print(f"Ошибка при выполнении SQL запроса: {sql_e}")
                        return jsonify([])
            else:
                # Для соц. адаптационного отдела показываем только не удаленные
                try:
                    records = SocialHelpRecord.query.filter_by(repatriant_id=repatriant_id, is_deleted=False).order_by(SocialHelpRecord.created_at.desc()).all()
                except Exception as e:
                    print(f"Поле is_deleted не существует, показываем все записи: {e}")
                    records = SocialHelpRecord.query.filter_by(repatriant_id=repatriant_id).order_by(SocialHelpRecord.created_at.desc()).all()

            return jsonify([record.to_dict() for record in records])

        elif request.method == 'POST':
            try:
                form_data = request.form
                files = request.files.getlist('documents')

                # Обрабатываем дату
                help_date = datetime.strptime(form_data.get('help_date'), '%Y-%m-%d').date() if form_data.get('help_date') else None

                # Сохраняем файлы
                document_paths = []
                if files:
                    for file in files:
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                saved_path = save_file(file, 'documents', f'social_{repatriant_id}_{uuid.uuid4().hex[:8]}')
                                if saved_path:
                                    document_paths.append(saved_path)

                # Определяем тип помощи для отображения
                help_type = form_data.get('help_type')
                custom_help_type = form_data.get('custom_help_type') if help_type == 'другое' else None

                # Создаем запись
                record = SocialHelpRecord(
                    repatriant_id=repatriant_id,
                    help_type=help_type,
                    custom_help_type=custom_help_type,
                    responsible=form_data.get('responsible'),
                    help_date=help_date,
                    amount=form_data.get('amount'),
                    documents_path=json.dumps(document_paths) if document_paths else None,
                    description=form_data.get('description'),
                    created_by=session.get('user_id')
                )

                db.session.add(record)
                db.session.commit()

                log_user_action(f'Добавлена запись о социальной помощи для репатрианта {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 201

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/social/<int:record_id>', methods=['PUT', 'DELETE'])
    @login_required
    def api_update_social(record_id):
        """Обновление или удаление записи о социальной помощи"""
        if request.method == 'PUT':
            try:
                record = SocialHelpRecord.query.get_or_404(record_id)
                form_data = request.form
                files = request.files.getlist('documents')

                # Обновляем данные
                if form_data.get('help_type'):
                    record.help_type = form_data.get('help_type')
                if form_data.get('custom_help_type'):
                    record.custom_help_type = form_data.get('custom_help_type') if form_data.get('help_type') == 'другое' else None
                if form_data.get('responsible') is not None:
                    record.responsible = form_data.get('responsible')
                if form_data.get('help_date'):
                    record.help_date = datetime.strptime(form_data.get('help_date'), '%Y-%m-%d').date()
                if form_data.get('amount') is not None:
                    record.amount = form_data.get('amount')
                if form_data.get('description') is not None:
                    record.description = form_data.get('description')

                # Обрабатываем новые файлы
                if files:
                    existing_docs = json.loads(record.documents_path) if record.documents_path else []
                    for file in files:
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                saved_path = save_file(file, 'documents', f'social_{record.repatriant_id}_{uuid.uuid4().hex[:8]}')
                                if saved_path:
                                    existing_docs.append(saved_path)
                    record.documents_path = json.dumps(existing_docs) if existing_docs else None

                db.session.commit()

                log_user_action(f'Обновлена запись о социальной помощи {record_id}', record.repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 200

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

        elif request.method == 'DELETE':
            try:
                record = SocialHelpRecord.query.get_or_404(record_id)
                repatriant_id = record.repatriant_id
                user_role = session.get('role')

                # ВСЕГДА используем мягкое удаление (soft delete) - помечаем как удаленное
                # Администратор видит все записи (включая удаленные)
                # Пользователь соц. адаптационного отдела видит только не удаленные
                try:
                    # Проверяем, существует ли поле в БД
                    db.session.execute(text('SELECT "IS_DELETED" FROM "SOCIAL_HELP_RECORDS" WHERE "ID" = :id LIMIT 1'), {'id': record_id})
                    # Если запрос прошел, поле существует - делаем мягкое удаление
                    record.is_deleted = True
                    record.deleted_at = datetime.utcnow()
                    record.deleted_by = session.get('user_id')
                    log_user_action(f'Помечена как удаленная запись о социальной помощи {record_id} (пользователь: {user_role})', repatriant_id)
                except Exception as e:
                    # Если поля не существуют, возвращаем ошибку с сообщением
                    return jsonify({
                        'success': False, 
                        'error': 'Поля для мягкого удаления не добавлены в БД. Запустите миграцию: python scripts/add_soft_delete_fields.py'
                    }), 400

                db.session.commit()
                return jsonify({'success': True}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/events/<int:repatriant_id>', methods=['GET', 'POST'])
    @login_required
    def api_events(repatriant_id):
        """API для работы с записями о мероприятиях"""
        if request.method == 'GET':
            # Для администратора показываем все записи (включая удаленные), для соц. адаптационного отдела только не удаленные
            user_role = session.get('role')

            if user_role == 'ADMIN':
                # Администратор видит все записи (включая удаленные)
                try:
                    # Пытаемся использовать обычный запрос с полем is_deleted
                    records = EventRecord.query.filter_by(repatriant_id=repatriant_id).order_by(EventRecord.created_at.desc()).all()
                except Exception as e:
                    # Если поле is_deleted не существует, используем прямой SQL запрос
                    print(f"Поле is_deleted не существует, используем прямой SQL: {e}")
                    try:
                        result = db.session.execute(text('''
                            SELECT "ID", "REPATRIANT_ID", "EVENT_NAME", "EVENT_START_DATE", "EVENT_END_DATE",
                                   "EVENT_LOCATION", "EVENT_TYPE", "EVENT_AMOUNT", "DESCRIPTION", "CREATED_AT", "CREATED_BY"
                            FROM "EVENT_RECORDS"
                            WHERE "REPATRIANT_ID" = :repatriant_id
                            ORDER BY "CREATED_AT" DESC
                        '''), {'repatriant_id': repatriant_id})

                        # Создаем словари вместо объектов модели
                        records_dict = []
                        for row in result:
                            records_dict.append({
                                'id': row[0],
                                'event_name': row[2],
                                'event_start_date': row[3].strftime('%Y-%m-%d') if row[3] else None,
                                'event_end_date': row[4].strftime('%Y-%m-%d') if row[4] else None,
                                'event_location': row[5],
                                'event_type': row[6],
                                'event_amount': float(row[7]) if row[7] else None,
                                'description': row[8],
                                'created_at': row[9].strftime('%Y-%m-%d %H:%M:%S') if row[9] else None,
                                'is_deleted': False,  # По умолчанию False, так как поле не существует
                                'deleted_at': None
                            })
                        return jsonify(records_dict)
                    except Exception as sql_e:
                        print(f"Ошибка при выполнении SQL запроса: {sql_e}")
                        return jsonify([])
            else:
                # Для соц. адаптационного отдела показываем только не удаленные
                try:
                    records = EventRecord.query.filter_by(repatriant_id=repatriant_id, is_deleted=False).order_by(EventRecord.created_at.desc()).all()
                except Exception as e:
                    print(f"Поле is_deleted не существует, показываем все записи: {e}")
                    records = EventRecord.query.filter_by(repatriant_id=repatriant_id).order_by(EventRecord.created_at.desc()).all()

            return jsonify([record.to_dict() for record in records])

        elif request.method == 'POST':
            try:
                form_data = request.form

                # Обрабатываем даты
                event_start_date = datetime.strptime(form_data.get('event_start_date'), '%Y-%m-%d').date() if form_data.get('event_start_date') else None
                event_end_date = datetime.strptime(form_data.get('event_end_date'), '%Y-%m-%d').date() if form_data.get('event_end_date') else None

                # Создаем запись
                record = EventRecord(
                    repatriant_id=repatriant_id,
                    event_name=form_data.get('event_name'),
                    event_start_date=event_start_date,
                    event_end_date=event_end_date,
                    event_location=form_data.get('event_location'),
                    event_type=form_data.get('event_type'),
                    event_amount=float(form_data.get('event_amount')) if form_data.get('event_amount') else None,
                    description=form_data.get('description'),
                    created_by=session.get('user_id')
                )

                db.session.add(record)
                db.session.commit()

                log_user_action(f'Добавлена запись о мероприятии для репатрианта {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 201

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/events/<int:record_id>', methods=['PUT', 'DELETE'])
    @login_required
    def api_update_event(record_id):
        """Обновление или удаление записи о мероприятии"""
        if request.method == 'PUT':
            try:
                record = EventRecord.query.get_or_404(record_id)
                form_data = request.form

                # Обновляем данные
                if form_data.get('event_name'):
                    record.event_name = form_data.get('event_name')
                if form_data.get('event_start_date'):
                    record.event_start_date = datetime.strptime(form_data.get('event_start_date'), '%Y-%m-%d').date()
                if form_data.get('event_end_date'):
                    record.event_end_date = datetime.strptime(form_data.get('event_end_date'), '%Y-%m-%d').date() if form_data.get('event_end_date') else None
                if form_data.get('event_location') is not None:
                    record.event_location = form_data.get('event_location')
                if form_data.get('event_type') is not None:
                    record.event_type = form_data.get('event_type')
                if form_data.get('event_amount'):
                    record.event_amount = float(form_data.get('event_amount')) if form_data.get('event_amount') else None
                if form_data.get('description') is not None:
                    record.description = form_data.get('description')

                db.session.commit()

                log_user_action(f'Обновлена запись о мероприятии {record_id}', record.repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 200

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

        elif request.method == 'DELETE':
            try:
                record = EventRecord.query.get_or_404(record_id)
                repatriant_id = record.repatriant_id
                user_role = session.get('role')

                # ВСЕГДА используем мягкое удаление (soft delete) - помечаем как удаленное
                # Администратор видит все записи (включая удаленные)
                # Пользователь соц. адаптационного отдела видит только не удаленные
                try:
                    # Проверяем, существует ли поле в БД
                    db.session.execute(text('SELECT "IS_DELETED" FROM "EVENT_RECORDS" WHERE "ID" = :id LIMIT 1'), {'id': record_id})
                    # Если запрос прошел, поле существует - делаем мягкое удаление
                    record.is_deleted = True
                    record.deleted_at = datetime.utcnow()
                    record.deleted_by = session.get('user_id')
                    log_user_action(f'Помечена как удаленная запись о мероприятии {record_id} (пользователь: {user_role})', repatriant_id)
                except Exception as e:
                    # Если поля не существуют, возвращаем ошибку с сообщением
                    return jsonify({
                        'success': False, 
                        'error': 'Поля для мягкого удаления не добавлены в БД. Запустите миграцию: python scripts/add_soft_delete_fields.py'
                    }), 400

                db.session.commit()
                return jsonify({'success': True}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/other/<int:repatriant_id>', methods=['GET', 'POST'])
    @login_required
    def api_other(repatriant_id):
        """API для работы с прочими записями"""
        if request.method == 'GET':
            # Для администратора показываем все записи (включая удаленные), для соц. адаптационного отдела только не удаленные
            user_role = session.get('role')

            if user_role == 'ADMIN':
                # Администратор видит все записи (включая удаленные)
                try:
                    # Пытаемся использовать обычный запрос с полем is_deleted
                    records = OtherRecord.query.filter_by(repatriant_id=repatriant_id).order_by(OtherRecord.created_at.desc()).all()
                except Exception as e:
                    # Если поле is_deleted не существует, используем прямой SQL запрос
                    print(f"Поле is_deleted не существует, используем прямой SQL: {e}")
                    try:
                        result = db.session.execute(text('''
                            SELECT "ID", "REPATRIANT_ID", "TITLE", "RECORD_DATE", "CATEGORY", 
                                   "CONTENT", "CREATED_AT", "CREATED_BY"
                            FROM "OTHER_RECORDS"
                            WHERE "REPATRIANT_ID" = :repatriant_id
                            ORDER BY "CREATED_AT" DESC
                        '''), {'repatriant_id': repatriant_id})

                        # Создаем словари вместо объектов модели
                        records_dict = []
                        for row in result:
                            records_dict.append({
                                'id': row[0],
                                'title': row[2],
                                'record_date': row[3].strftime('%Y-%m-%d') if row[3] else None,
                                'category': row[4],
                                'content': row[5],
                                'created_at': row[6].strftime('%Y-%m-%d %H:%M:%S') if row[6] else None,
                                'is_deleted': False,  # По умолчанию False, так как поле не существует
                                'deleted_at': None
                            })
                        return jsonify(records_dict)
                    except Exception as sql_e:
                        print(f"Ошибка при выполнении SQL запроса: {sql_e}")
                        return jsonify([])
            else:
                # Для соц. адаптационного отдела показываем только не удаленные
                try:
                    records = OtherRecord.query.filter_by(repatriant_id=repatriant_id, is_deleted=False).order_by(OtherRecord.created_at.desc()).all()
                except Exception as e:
                    print(f"Поле is_deleted не существует, показываем все записи: {e}")
                    records = OtherRecord.query.filter_by(repatriant_id=repatriant_id).order_by(OtherRecord.created_at.desc()).all()

            return jsonify([record.to_dict() for record in records])

        elif request.method == 'POST':
            try:
                form_data = request.form

                # Обрабатываем дату
                record_date = datetime.strptime(form_data.get('record_date'), '%Y-%m-%d').date() if form_data.get('record_date') else None

                # Создаем запись
                record = OtherRecord(
                    repatriant_id=repatriant_id,
                    title=form_data.get('title'),
                    record_date=record_date,
                    category=form_data.get('category'),
                    content=form_data.get('content'),
                    created_by=session.get('user_id')
                )

                db.session.add(record)
                db.session.commit()

                log_user_action(f'Добавлена прочая запись для репатрианта {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 201

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/housing/<int:record_id>/restore', methods=['POST'])
    @admin_required
    def api_restore_housing(record_id):
        """Восстановление удаленной записи об аренде жилья (только для администратора)"""
        try:
            record = HousingRecord.query.get_or_404(record_id)
            record.is_deleted = False
            record.deleted_at = None
            record.deleted_by = None
            db.session.commit()

            log_user_action(f'Восстановлена запись об аренде жилья {record_id}', record.repatriant_id)

            return jsonify({'success': True, 'record': record.to_dict()}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/social/<int:record_id>/restore', methods=['POST'])
    @admin_required
    def api_restore_social(record_id):
        """Восстановление удаленной записи о социальной помощи (только для администратора)"""
        try:
            record = SocialHelpRecord.query.get_or_404(record_id)
            record.is_deleted = False
            record.deleted_at = None
            record.deleted_by = None
            db.session.commit()

            log_user_action(f'Восстановлена запись о социальной помощи {record_id}', record.repatriant_id)

            return jsonify({'success': True, 'record': record.to_dict()}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/events/<int:record_id>/restore', methods=['POST'])
    @admin_required
    def api_restore_event(record_id):
        """Восстановление удаленной записи о мероприятии (только для администратора)"""
        try:
            record = EventRecord.query.get_or_404(record_id)
            record.is_deleted = False
            record.deleted_at = None
            record.deleted_by = None
            db.session.commit()

            log_user_action(f'Восстановлена запись о мероприятии {record_id}', record.repatriant_id)

            return jsonify({'success': True, 'record': record.to_dict()}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/other/<int:record_id>/restore', methods=['POST'])
    @admin_required
    def api_restore_other(record_id):
        """Восстановление удаленной прочей записи (только для администратора)"""
        try:
            record = OtherRecord.query.get_or_404(record_id)
            record.is_deleted = False
            record.deleted_at = None
            record.deleted_by = None
            db.session.commit()

            log_user_action(f'Восстановлена прочая запись {record_id}', record.repatriant_id)

            return jsonify({'success': True, 'record': record.to_dict()}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/other/<int:record_id>', methods=['PUT', 'DELETE'])
    @login_required
    def api_update_other(record_id):
        """Обновление или удаление прочей записи"""
        if request.method == 'PUT':
            try:
                record = OtherRecord.query.get_or_404(record_id)
                form_data = request.form

                # Обновляем данные
                if form_data.get('title'):
                    record.title = form_data.get('title')
                if form_data.get('record_date'):
                    record.record_date = datetime.strptime(form_data.get('record_date'), '%Y-%m-%d').date()
                if form_data.get('category') is not None:
                    record.category = form_data.get('category')
                if form_data.get('content'):
                    record.content = form_data.get('content')

                db.session.commit()

                log_user_action(f'Обновлена прочая запись {record_id}', record.repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 200

            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

        elif request.method == 'DELETE':
            try:
                record = OtherRecord.query.get_or_404(record_id)
                repatriant_id = record.repatriant_id
                user_role = session.get('role')

                # ВСЕГДА используем мягкое удаление (soft delete) - помечаем как удаленное
                # Администратор видит все записи (включая удаленные)
                # Пользователь соц. адаптационного отдела видит только не удаленные
                try:
                    # Проверяем, существует ли поле в БД
                    db.session.execute(text('SELECT "IS_DELETED" FROM "OTHER_RECORDS" WHERE "ID" = :id LIMIT 1'), {'id': record_id})
                    # Если запрос прошел, поле существует - делаем мягкое удаление
                    record.is_deleted = True
                    record.deleted_at = datetime.utcnow()
                    record.deleted_by = session.get('user_id')
                    log_user_action(f'Помечена как удаленная прочая запись {record_id} (пользователь: {user_role})', repatriant_id)
                except Exception as e:
                    # Если поля не существуют, возвращаем ошибку с сообщением
                    return jsonify({
                        'success': False, 
                        'error': 'Поля для мягкого удаления не добавлены в БД. Запустите миграцию: python scripts/add_soft_delete_fields.py'
                    }), 400

                db.session.commit()
                return jsonify({'success': True}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

