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


def register_repatriant_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    # Редактирование репатрианта
    @app.route('/edit/<int:id>', methods=['GET', 'POST'])
    @login_required
    def edit_repatriant(id):
        # Социально адаптационный отдел и жилищный отдел не могут редактировать основную информацию
        if session.get('role') in ['SOCIAL_ADAPTATION', 'HOUSING_DEPARTMENT']:
            flash('У вас нет доступа к редактированию основной информации репатриантов', 'error')
            return redirect(url_for('view_repatriant', id=id))
        repatriant = Repatriant.query.get_or_404(id)

        # Получаем существующих детей и членов семьи для отображения
        # Загружаем сразу, чтобы они были доступны и при GET, и при POST запросах
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        # Отладочная информация
        print(f"DEBUG: Загружено детей для репатрианта {id}: {len(children)}")
        print(f"DEBUG: Загружено членов семьи для репатрианта {id}: {len(family_members)}")

        if request.method == 'POST':
            try:
                # Обновляем данные
                # Обрабатываем числовые поля - пустые строки преобразуем в None
                kod_value = request.form.get('kod')
                if kod_value and kod_value.strip():
                    kod_value = kod_value.strip()  # Убираем пробелы, но сохраняем как строку
                else:
                    kod_value = None

                repatriant.kod = kod_value
                repatriant.f = request.form.get('f')
                repatriant.i = request.form.get('i')
                repatriant.o = request.form.get('o')
                repatriant.f_hist = request.form.get('f_hist')
                repatriant.strana_proj = request.form.get('strana_proj')
                repatriant.from_loc = request.form.get('from_loc')
                repatriant.reshenie_komissii = bool(request.form.get('reshenie_komissii'))
                repatriant.date_r = datetime.strptime(request.form.get('date_r'), '%Y-%m-%d').date() if request.form.get('date_r') else None
                repatriant.sex = request.form.get('sex')
                repatriant.rojd_loc = request.form.get('rojd_loc')
                repatriant.sem_poloj = request.form.get('sem_poloj')
                repatriant.rep_status = datetime.strptime(request.form.get('rep_status'), '%Y-%m-%d').date() if request.form.get('rep_status') else None
                repatriant.date_registration = datetime.strptime(request.form.get('date_registration'), '%Y-%m-%d').date() if request.form.get('date_registration') else None
                repatriant.doc_lichn = request.form.get('doc_lichn')
                repatriant.n_doc_lichn = request.form.get('n_doc_lichn')
                repatriant.adres = request.form.get('adres')
                repatriant.tel = request.form.get('tel')
                repatriant.mail = request.form.get('mail')
                # Обработка национальности: если выбрано "Другое", берем значение из rezerv_other
                # Нормализуем значение (преобразуем женский род в мужской согласно стандартизации)
                rezerv_value = request.form.get('rezerv')
                if rezerv_value == 'OTHER':
                    rezerv_value = request.form.get('rezerv_other', '').strip()

                # Нормализация национальности (женский род -> мужской род)
                if rezerv_value:
                    rezerv_value = normalize_nationality_value(rezerv_value)

                repatriant.rezerv = rezerv_value if rezerv_value else None
                repatriant.dop_info = request.form.get('dop_info')

                # Преобразуем текстовые поля в верхний регистр перед сохранением
                exclude_fields = {'password_hash', 'avatar_path', 'documents_path', 'file', 'photo', 'file_jil', 'f_name', 'f_name_jil', 'mail'}
                uppercase_string_fields(repatriant, exclude_fields)

                # Обрабатываем загруженные файлы
                # Загружаем PDF документы (если новый файл загружен)
                if 'documents' in request.files:
                    documents_file = request.files['documents']
                    if documents_file and documents_file.filename:
                        # Удаляем старый файл если есть
                        if repatriant.documents_path:
                            delete_file(repatriant.documents_path)
                        # Сохраняем новый файл
                        repatriant.documents_path = save_file(documents_file, 'documents', f'doc_{id}')

                # Обрабатываем данные о детях
                children_data = request.form.get('children_data')
                if children_data:
                    try:
                        # Удаляем старых детей
                        Child.query.filter_by(list_id=id).delete()

                        # Добавляем новых детей
                        children_list = json.loads(children_data)
                        for child_data in children_list:
                            # Получаем следующий ID для ребенка
                            max_child_id = db.session.query(db.func.max(Child.id_child)).scalar()
                            next_child_id = (max_child_id or 0) + 1

                            child = Child(
                                id_child=next_child_id,
                                list_id=id,
                                step_rod=child_data.get('step_rod'),
                                fio=child_data.get('fio'),
                                god_r=child_data.get('god_r'),
                                mesto_r=child_data.get('mesto_r'),
                                grajdanstvo=child_data.get('grajdanstvo'),
                                nacionalnost=child_data.get('nacionalnost'),
                                lives_with_parent=child_data.get('lives_with_parent', False)
                            )
                            # Преобразуем текстовые поля в верхний регистр
                            uppercase_string_fields(child, {})
                            db.session.add(child)
                    except json.JSONDecodeError:
                        flash('Ошибка при обработке данных о детях', 'warning')

                # Обрабатываем данные о семье
                family_data = request.form.get('family_data')
                if family_data:
                    try:
                        # Удаляем старых членов семьи
                        FamilyMember.query.filter_by(list_id=id).delete()

                        # Добавляем новых членов семьи
                        family_list = json.loads(family_data)
                        for family_data_item in family_list:
                            # Получаем следующий ID для члена семьи
                            max_family_id = db.session.query(db.func.max(FamilyMember.id_family)).scalar()
                            next_family_id = (max_family_id or 0) + 1

                            family_member = FamilyMember(
                                id_family=next_family_id,
                                list_id=id,
                                step_rod=family_data_item.get('step_rod'),
                                fio=family_data_item.get('fio'),
                                god_r=family_data_item.get('god_r'),
                                grajdanstvo=family_data_item.get('grajdanstvo'),
                                nacionalnost=family_data_item.get('nacionalnost'),
                                adres=family_data_item.get('adres'),
                                lives_with_parent=family_data_item.get('lives_with_parent', False)
                            )
                            # Преобразуем текстовые поля в верхний регистр
                            uppercase_string_fields(family_member, {})
                            db.session.add(family_member)
                    except json.JSONDecodeError:
                        flash('Ошибка при обработке данных о семье', 'warning')

                db.session.commit()

                log_user_action(f'Отредактирован репатриант: {repatriant.f} {repatriant.i} {repatriant.o}', id)

                flash('Данные репатрианта успешно обновлены!', 'success')
                return redirect(url_for('view_repatriant', id=id))
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка при обновлении: {str(e)}', 'error')
                # Перезагружаем детей и членов семьи после ошибки, так как они могли быть удалены
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        return render_template('edit.html', repatriant=repatriant, children=children, family_members=family_members)

    # Удаление репатрианта
    @app.route('/delete/<int:id>', methods=['POST'])
    @login_required
    def delete_repatriant(id):
        print(f"DEBUG: Delete request received for ID: {id}")  # Отладочный вывод
        repatriant = Repatriant.query.get_or_404(id)
        try:
            # Удаляем связанных детей и членов семьи
            Child.query.filter_by(list_id=id).delete()
            FamilyMember.query.filter_by(list_id=id).delete()

            # Удаляем репатрианта
            db.session.delete(repatriant)
            db.session.commit()

            log_user_action(f'Удален репатриант: {repatriant.f} {repatriant.i} {repatriant.o}', id)

            flash('Репатриант успешно удален!', 'success')
            print(f"DEBUG: Successfully deleted repatriant ID: {id}")  # Отладочный вывод
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при удалении: {str(e)}', 'error')
            print(f"DEBUG: Error deleting repatriant ID {id}: {e}")  # Отладочный вывод

        return redirect(url_for('search'))

