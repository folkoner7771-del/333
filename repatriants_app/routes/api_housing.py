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


def register_api_housing_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    # API endpoints для жилищного отдела

    @app.route('/api/search-repatriants')
    @login_required
    def api_search_repatriants():
        """API для поиска репатриантов"""
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify([])

        try:
            # Поиск по ФИО или коду
            results = Repatriant.query.filter(
                db.or_(
                    db.func.concat(Repatriant.f, ' ', Repatriant.i, ' ', Repatriant.o).ilike(f'%{query}%'),
                    Repatriant.kod.ilike(f'%{query}%')
                )
            ).limit(20).all()

            return jsonify([{
                'id': r.id,
                'f': r.f or '',
                'i': r.i or '',
                'o': r.o or '',
                'kod': r.kod or '',
                'date_r': r.date_r.strftime('%Y-%m-%d') if r.date_r else None,
                'rep_status': r.rep_status.strftime('%Y-%m-%d') if r.rep_status else None
            } for r in results])
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/repatriant/<int:repatriant_id>/family')
    @login_required
    def api_repatriant_family(repatriant_id):
        """API для получения информации о детях и семье репатрианта"""
        try:
            children = Child.query.filter_by(list_id=repatriant_id).all()
            family_members = FamilyMember.query.filter_by(list_id=repatriant_id).all()

            return jsonify({
                'children': [{
                    'fio': child.fio or '',
                    'step_rod': child.step_rod or '',
                    'god_r': child.god_r or '',
                    'mesto_r': child.mesto_r or '',
                    'grajdanstvo': child.grajdanstvo or ''
                } for child in children],
                'family_members': [{
                    'fio': member.fio or '',
                    'step_rod': member.step_rod or '',
                    'god_r': member.god_r or '',
                    'grajdanstvo': member.grajdanstvo or '',
                    'adres': member.adres or ''
                } for member in family_members]
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route('/api/housing-department/<int:repatriant_id>', methods=['GET', 'POST'])
    @login_required
    def api_housing_department(repatriant_id):
        """API для работы с записями жилищного отдела"""
        if request.method == 'GET':
            try:
                records = HousingDepartmentRecord.query.filter_by(
                    repatriant_id=repatriant_id,
                    is_deleted=False
                ).order_by(HousingDepartmentRecord.created_at.desc()).all()
                return jsonify([record.to_dict() for record in records])
            except Exception as e:
                return jsonify({'error': str(e)}), 400

        elif request.method == 'POST':
            try:
                form_data = request.form
                files = request.files.getlist('documents')

                # Валидация: если жилье не получено, статус жилья и адрес должны быть пустыми
                received_housing = form_data.get('received_housing') == 'true'
                housing_acquisition = form_data.get('housing_acquisition') if received_housing else None
                address = form_data.get('address') if received_housing else None

                # Сначала создаем запись без файлов, чтобы получить ID
                # family_composition удален из базы - данные хранятся только в таблицах CHILDREN и FAMILY
                record = HousingDepartmentRecord(
                    repatriant_id=repatriant_id,
                    category=form_data.get('category'),
                    received_housing=received_housing,
                    housing_type=form_data.get('housing_type'),
                    housing_acquisition=housing_acquisition,
                    address=address,
                    # family_composition удален из базы данных
                    has_warrant=form_data.get('has_warrant') == 'true',
                    repair_amount=float(form_data.get('repair_amount')) if form_data.get('repair_amount') else None,
                    documents_path=None,  # Временно без файлов
                    notes=form_data.get('notes'),
                    protocol_number=form_data.get('protocol_number'),
                    created_by=session.get('user_id')
                )

                # Преобразуем текстовые поля в верхний регистр
                uppercase_string_fields(record, {'notes'})

                db.session.add(record)
                db.session.flush()  # Получаем ID записи без коммита

                # Теперь сохраняем файлы с правильным именем: jilotdel_{record_id}_{hash}.pdf
                # Получаем названия документов из form_data
                document_names = form_data.getlist('document_names')
                document_list = []
                if files:
                    for index, file in enumerate(files):
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                # Используем формат: jilotdel_{record_id}_{hash}.pdf
                                saved_path = save_file(file, 'documents', f'jilotdel_{record.id}')
                                if saved_path:
                                    # Получаем название документа (если указано)
                                    doc_name = document_names[index].strip() if index < len(document_names) else ''
                                    document_list.append({
                                        'path': saved_path,
                                        'name': doc_name
                                    })

                # Обновляем запись с путями к файлам и названиями
                if document_list:
                    record.documents_path = json.dumps(document_list)

                # Обновляем таблицы CHILDREN и FAMILY из family_composition
                # ВАЖНО: family_composition используется только как временный контейнер данных из формы
                # Реальные данные хранятся ТОЛЬКО в таблицах CHILDREN и FAMILY
                family_composition_data = form_data.get('family_composition')
                if family_composition_data:
                    try:
                        family_composition = json.loads(family_composition_data)

                        # Обновляем детей в таблице CHILDREN
                        if 'children' in family_composition:
                            # Удаляем старых детей для этого репатрианта
                            Child.query.filter_by(list_id=repatriant_id).delete()

                            # Добавляем новых детей в таблицу CHILDREN
                            for child_data in family_composition['children']:
                                max_child_id = db.session.query(db.func.max(Child.id_child)).scalar()
                                next_child_id = (max_child_id or 0) + 1

                                child = Child(
                                    id_child=next_child_id,
                                    list_id=repatriant_id,
                                    step_rod=child_data.get('step_rod'),
                                    fio=child_data.get('fio'),
                                    god_r=child_data.get('god_r'),
                                    mesto_r=child_data.get('mesto_r'),
                                    grajdanstvo=child_data.get('grajdanstvo'),
                                    nacionalnost=child_data.get('nacionalnost'),
                                    lives_with_parent=child_data.get('lives_with_parent', False)
                                )
                                uppercase_string_fields(child, {})
                                db.session.add(child)

                        # Обновляем членов семьи в таблице FAMILY
                        if 'family_members' in family_composition:
                            # Удаляем старых членов семьи для этого репатрианта
                            FamilyMember.query.filter_by(list_id=repatriant_id).delete()

                            # Добавляем новых членов семьи в таблицу FAMILY
                            for family_data_item in family_composition['family_members']:
                                max_family_id = db.session.query(db.func.max(FamilyMember.id_family)).scalar()
                                next_family_id = (max_family_id or 0) + 1

                                family_member = FamilyMember(
                                    id_family=next_family_id,
                                    list_id=repatriant_id,
                                    step_rod=family_data_item.get('step_rod'),
                                    fio=family_data_item.get('fio'),
                                    god_r=family_data_item.get('god_r'),
                                    grajdanstvo=family_data_item.get('grajdanstvo'),
                                    nacionalnost=family_data_item.get('nacionalnost'),
                                    adres=family_data_item.get('adres'),
                                    lives_with_parent=family_data_item.get('lives_with_parent', False)
                                )
                                uppercase_string_fields(family_member, {})
                                db.session.add(family_member)
                    except (json.JSONDecodeError, Exception) as e:
                        print(f'Ошибка при обновлении детей и семьи: {e}')

                db.session.commit()

                log_user_action(f'Добавлена запись жилищного отдела для репатрианта {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/housing-department/<int:record_id>', methods=['PUT', 'DELETE'])
    @login_required
    def api_update_housing_department_record(record_id):
        """API для обновления или удаления записи жилищного отдела"""
        if request.method == 'PUT':
            try:
                record = HousingDepartmentRecord.query.get_or_404(record_id)
                form_data = request.form
                files = request.files.getlist('documents')

                # Обновляем поля записи
                if form_data.get('category') is not None:
                    record.category = form_data.get('category')
                if form_data.get('received_housing') is not None:
                    received_housing = form_data.get('received_housing') == 'true'
                    record.received_housing = received_housing
                    # Валидация: если жилье не получено, очищаем статус жилья и адрес
                    if not received_housing:
                        record.housing_acquisition = None
                        record.address = None
                if form_data.get('housing_type') is not None:
                    record.housing_type = form_data.get('housing_type')
                if form_data.get('housing_acquisition') is not None:
                    # Валидация: статус жилья можно установить только если жилье получено
                    if record.received_housing:
                        record.housing_acquisition = form_data.get('housing_acquisition')
                    else:
                        record.housing_acquisition = None
                if form_data.get('address') is not None:
                    # Валидация: адрес можно установить только если жилье получено
                    if record.received_housing:
                        record.address = form_data.get('address')
                    else:
                        record.address = None
                # НЕ обновляем family_composition при редактировании - это только снимок на момент создания записи
                # Основной источник данных - таблицы CHILDREN и FAMILY
                if form_data.get('has_warrant') is not None:
                    record.has_warrant = form_data.get('has_warrant') == 'true'
                if form_data.get('repair_amount') is not None:
                    record.repair_amount = float(form_data.get('repair_amount')) if form_data.get('repair_amount') else None
                if form_data.get('notes') is not None:
                    record.notes = form_data.get('notes')
                if form_data.get('protocol_number') is not None:
                    record.protocol_number = form_data.get('protocol_number')

                # Обрабатываем документы
                # Получаем список существующих документов, которые нужно сохранить
                existing_documents_json = form_data.get('existing_documents')
                if existing_documents_json:
                    try:
                        existing_documents = json.loads(existing_documents_json)
                    except json.JSONDecodeError:
                        existing_documents = []
                else:
                    # Если не передано, используем старые документы
                    existing_documents = json.loads(record.documents_path) if record.documents_path else []

                # Обрабатываем новые файлы с названиями
                document_names = form_data.getlist('document_names')
                new_documents = []
                if files:
                    for index, file in enumerate(files):
                        if file and file.filename:
                            if file.filename.lower().endswith('.pdf'):
                                saved_path = save_file(file, 'documents', f'jilotdel_{record.id}')
                                if saved_path:
                                    # Получаем название документа (если указано)
                                    doc_name = document_names[index].strip() if index < len(document_names) else ''
                                    new_documents.append({
                                        'path': saved_path,
                                        'name': doc_name
                                    })

                # Объединяем существующие и новые документы
                all_documents = existing_documents + new_documents
                if all_documents:
                    record.documents_path = json.dumps(all_documents)
                else:
                    record.documents_path = None

                # Обновляем таблицы CHILDREN и FAMILY из family_composition
                # ВАЖНО: family_composition используется только как временный контейнер данных из формы
                # Реальные данные хранятся ТОЛЬКО в таблицах CHILDREN и FAMILY
                if form_data.get('family_composition') is not None:
                    family_composition_data = form_data.get('family_composition')
                    try:
                        family_composition = json.loads(family_composition_data)

                        # Обновляем детей в таблице CHILDREN
                        if 'children' in family_composition:
                            # Удаляем старых детей для этого репатрианта
                            Child.query.filter_by(list_id=record.repatriant_id).delete()

                            # Добавляем новых детей в таблицу CHILDREN
                            for child_data in family_composition['children']:
                                max_child_id = db.session.query(db.func.max(Child.id_child)).scalar()
                                next_child_id = (max_child_id or 0) + 1

                                child = Child(
                                    id_child=next_child_id,
                                    list_id=record.repatriant_id,
                                    step_rod=child_data.get('step_rod'),
                                    fio=child_data.get('fio'),
                                    god_r=child_data.get('god_r'),
                                    mesto_r=child_data.get('mesto_r'),
                                    grajdanstvo=child_data.get('grajdanstvo'),
                                    nacionalnost=child_data.get('nacionalnost'),
                                    lives_with_parent=child_data.get('lives_with_parent', False)
                                )
                                uppercase_string_fields(child, {})
                                db.session.add(child)

                        # Обновляем членов семьи в таблице FAMILY
                        if 'family_members' in family_composition:
                            # Удаляем старых членов семьи для этого репатрианта
                            FamilyMember.query.filter_by(list_id=record.repatriant_id).delete()

                            # Добавляем новых членов семьи в таблицу FAMILY
                            for family_data_item in family_composition['family_members']:
                                max_family_id = db.session.query(db.func.max(FamilyMember.id_family)).scalar()
                                next_family_id = (max_family_id or 0) + 1

                                family_member = FamilyMember(
                                    id_family=next_family_id,
                                    list_id=record.repatriant_id,
                                    step_rod=family_data_item.get('step_rod'),
                                    fio=family_data_item.get('fio'),
                                    god_r=family_data_item.get('god_r'),
                                    grajdanstvo=family_data_item.get('grajdanstvo'),
                                    nacionalnost=family_data_item.get('nacionalnost'),
                                    adres=family_data_item.get('adres'),
                                    lives_with_parent=family_data_item.get('lives_with_parent', False)
                                )
                                uppercase_string_fields(family_member, {})
                                db.session.add(family_member)
                    except (json.JSONDecodeError, Exception) as e:
                        print(f'Ошибка при обновлении детей и семьи: {e}')

                # family_composition НЕ сохраняем в базе - данные только в CHILDREN и FAMILY

                # Преобразуем текстовые поля в верхний регистр
                uppercase_string_fields(record, {'notes'})

                db.session.commit()
                log_user_action(f'Обновлена запись жилищного отдела {record_id}', record.repatriant_id)

                return jsonify({'success': True, 'record': record.to_dict()}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

        elif request.method == 'DELETE':
            try:
                record = HousingDepartmentRecord.query.get_or_404(record_id)
                repatriant_id = record.repatriant_id

                # Мягкое удаление
                record.is_deleted = True
                record.deleted_at = datetime.utcnow()
                record.deleted_by = session.get('user_id')

                db.session.commit()
                log_user_action(f'Удалена запись жилищного отдела {record_id}', repatriant_id)

                return jsonify({'success': True}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400

    @app.route('/api/housing-queue', methods=['GET', 'POST'])
    @login_required
    def api_housing_queue():
        """API для работы с очередью жилищного отдела"""
        if request.method == 'GET':
            try:
                # Получаем активные записи очереди
                queue_items = HousingQueue.query.filter_by(is_active=True).all()

                # Рассчитываем баллы и обновляем позиции
                for item in queue_items:
                    item.total_score = item.calculate_score()

                db.session.commit()

                # Сортируем по баллам (убывание) и времени добавления
                queue_items = HousingQueue.query.filter_by(is_active=True).order_by(
                    HousingQueue.total_score.desc(),
                    HousingQueue.added_at.asc()
                ).all()

                # Получаем информацию о репатриантах
                result = []
                for idx, item in enumerate(queue_items):
                    item.queue_position = idx + 1
                    repatriant = Repatriant.query.get(item.repatriant_id)
                    result.append({
                        'id': item.id,
                        'repatriant_id': item.repatriant_id,
                        'repatriant_name': f"{repatriant.f} {repatriant.i} {repatriant.o}" if repatriant else f"Репатриант #{item.repatriant_id}",
                        'has_children': item.has_children,
                        'has_work': item.has_work,
                        'has_law_violations': item.has_law_violations,
                        'total_score': item.total_score,
                        'queue_position': item.queue_position,
                        'added_at': item.added_at.strftime('%Y-%m-%d %H:%M:%S') if item.added_at else None
                    })

                db.session.commit()
                return jsonify(result)
            except Exception as e:
                return jsonify({'error': str(e)}), 400

        elif request.method == 'POST':
            try:
                data = request.json
                repatriant_id = data.get('repatriant_id')

                if not repatriant_id:
                    return jsonify({'success': False, 'error': 'repatriant_id обязателен'}), 400

                # Проверяем, не добавлен ли уже в очередь
                existing = HousingQueue.query.filter_by(
                    repatriant_id=repatriant_id,
                    is_active=True
                ).first()

                if existing:
                    return jsonify({'success': False, 'error': 'Репатриант уже в очереди'}), 400

                # Создаем запись в очереди
                queue_item = HousingQueue(
                    repatriant_id=repatriant_id,
                    has_children=data.get('has_children', False),
                    has_work=data.get('has_work', False),
                    has_law_violations=data.get('has_law_violations', False),
                    added_by=session.get('user_id')
                )

                # Рассчитываем балл
                queue_item.total_score = queue_item.calculate_score()

                db.session.add(queue_item)
                db.session.commit()

                log_user_action(f'Добавлен в очередь жилищного отдела репатриант {repatriant_id}', repatriant_id)

                return jsonify({'success': True, 'queue_item': queue_item.to_dict()}), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'error': str(e)}), 400


