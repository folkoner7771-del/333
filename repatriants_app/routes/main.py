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


def register_main_routes(app):
    """Регистрирует маршруты на переданном Flask-приложении."""

    # Главная страница перенаправляет на регистрацию
    @app.route('/')
    def home_redirect():
        return redirect(url_for('register'))

    # Дашборд
    @app.route('/dashboard')
    @login_required
    def dashboard():
        total_repatriants = Repatriant.query.count()
        today_registrations = Repatriant.query.filter(
            db.func.date(Repatriant.rep_status) == datetime.now().date()
        ).count()

        return render_template('dashboard.html', 
                             total_repatriants=total_repatriants,
                             today_registrations=today_registrations)

    # Страница регистрации нового репатрианта
    @app.route('/register', methods=['GET', 'POST'])
    @login_required
    def register():
        # Социально адаптационный отдел и жилищный отдел не могут регистрировать
        if session.get('role') in ['SOCIAL_ADAPTATION', 'HOUSING_DEPARTMENT']:
            flash('У вас нет доступа к регистрации репатриантов', 'error')
            return redirect(url_for('search'))
        if request.method == 'POST':
            try:
                # Получаем данные из формы
                # Обрабатываем поле kod - может содержать буквы и цифры
                kod_value = request.form.get('kod')
                if kod_value and kod_value.strip():
                    kod_value = kod_value.strip()  # Убираем пробелы, но сохраняем как строку
                else:
                    kod_value = None

                # Генерируем новый ID
                max_id = db.session.query(db.func.max(Repatriant.id)).scalar()
                next_id = (max_id or 0) + 1

                # Обрабатываем даты с проверкой на ошибки
                date_r = None
                if request.form.get('date_r'):
                    try:
                        date_r = datetime.strptime(request.form.get('date_r'), '%Y-%m-%d').date()
                    except ValueError as e:
                        flash(f'Ошибка в дате рождения: {str(e)}', 'error')
                        raise e

                rep_status = None
                if request.form.get('rep_status'):
                    try:
                        rep_status = datetime.strptime(request.form.get('rep_status'), '%Y-%m-%d').date()
                    except ValueError as e:
                        flash(f'Ошибка в дате статуса: {str(e)}', 'error')
                        raise e

                date_registration = None
                if request.form.get('date_registration'):
                    try:
                        date_registration = datetime.strptime(request.form.get('date_registration'), '%Y-%m-%d').date()
                    except ValueError as e:
                        flash(f'Ошибка в дате регистрации: {str(e)}', 'error')
                        raise e

                # Обрабатываем загруженные файлы
                documents_path = None
                avatar_path = None

                # Проверяем, есть ли предварительно загруженный PDF
                uploaded_pdf_path = request.form.get('uploaded_pdf_path')
                if uploaded_pdf_path:
                    # Перемещаем файл из временной папки на диски D/E
                    temp_full_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_pdf_path)
                    if os.path.exists(temp_full_path):
                        # Создаем постоянное имя файла
                        permanent_filename = f"doc_{next_id}_{uuid.uuid4().hex[:8]}.pdf"

                        # Выбираем лучший диск для сохранения
                        best_disk_path = get_best_disk()
                        permanent_path = os.path.join(best_disk_path, permanent_filename)

                        # Создаем папку если не существует
                        os.makedirs(best_disk_path, exist_ok=True)

                        # Перемещаем файл на диск (используем shutil.move для междискового перемещения)
                        shutil.move(temp_full_path, permanent_path)
                        documents_path = f"documents/{permanent_filename}"

                        print(f"PDF перемещен с {temp_full_path} на {permanent_path}")
                else:
                    # Загружаем PDF документы (если новый файл загружен)
                    if 'documents' in request.files:
                        documents_file = request.files['documents']
                        if documents_file and documents_file.filename:
                            documents_path = save_file(documents_file, 'documents', f'doc_{next_id}')

                # Обрабатываем вырезанную аватарку
                if 'cropped_avatar' in request.files:
                    avatar_file = request.files['cropped_avatar']
                    if avatar_file and avatar_file.filename:
                        avatar_path = save_file(avatar_file, 'avatars', f'avatar_{next_id}')

                repatriant = Repatriant(
                    id=next_id,
                    kod=kod_value,
                    f=request.form.get('f'),
                    i=request.form.get('i'),
                    o=request.form.get('o'),
                    f_hist=request.form.get('f_hist'),
                    strana_proj=request.form.get('strana_proj'),
                    from_loc=request.form.get('from_loc'),
                    reshenie_komissii=bool(request.form.get('reshenie_komissii')),
                    date_r=date_r,
                    sex=request.form.get('sex'),
                    rojd_loc=request.form.get('rojd_loc'),
                    sem_poloj=request.form.get('sem_poloj'),
                    rep_status=rep_status,
                    date_registration=date_registration,  # Получаем дату регистрации из формы
                    doc_lichn=request.form.get('doc_lichn'),
                    n_doc_lichn=request.form.get('n_doc_lichn'),
                    adres=request.form.get('adres'),
                    tel=request.form.get('tel'),
                    mail=request.form.get('mail'),
                    rezerv=normalize_nationality_value(request.form.get('rezerv_other', '').strip() if request.form.get('rezerv') == 'OTHER' else (request.form.get('rezerv') or '')),
                    dop_info=request.form.get('dop_info'),
                    documents_path=documents_path,
                    avatar_path=avatar_path
                )

                # Преобразуем текстовые поля в верхний регистр перед сохранением
                exclude_fields = {'password_hash', 'avatar_path', 'documents_path', 'file', 'photo', 'file_jil', 'f_name', 'f_name_jil', 'mail'}
                uppercase_string_fields(repatriant, exclude_fields)

                db.session.add(repatriant)
                db.session.flush()  # Получаем ID репатрианта

                # Обрабатываем данные о детях
                children_data = request.form.get('children_data')
                if children_data:
                    try:
                        children_list = json.loads(children_data)
                        for child_data in children_list:
                            # Получаем следующий ID для ребенка
                            max_child_id = db.session.query(db.func.max(Child.id_child)).scalar()
                            next_child_id = (max_child_id or 0) + 1

                            child = Child(
                                id_child=next_child_id,
                                list_id=repatriant.id,
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
                        family_list = json.loads(family_data)
                        for family_data_item in family_list:
                            # Получаем следующий ID для члена семьи
                            max_family_id = db.session.query(db.func.max(FamilyMember.id_family)).scalar()
                            next_family_id = (max_family_id or 0) + 1

                            family_member = FamilyMember(
                                id_family=next_family_id,
                                list_id=repatriant.id,
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

                log_user_action(f'Зарегистрирован репатриант: {repatriant.f} {repatriant.i} {repatriant.o}', repatriant.id)

                flash('Репатриант успешно зарегистрирован!', 'success')
                return redirect(url_for('register'))
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка при регистрации: {str(e)}', 'error')

                # Передаем данные формы обратно в шаблон для сохранения
                form_data = {
                    'registr': request.form.get('registr', ''),
                    'f': request.form.get('f', ''),
                    'i': request.form.get('i', ''),
                    'o': request.form.get('o', ''),
                    'f_hist': request.form.get('f_hist', ''),
                    'strana_proj': request.form.get('strana_proj', ''),
                    'from_loc': request.form.get('from_loc', ''),
                    'reshenie_komissii': bool(request.form.get('reshenie_komissii')),
                    'date_r': request.form.get('date_r', ''),
                    'sex': request.form.get('sex', ''),
                    'rojd_loc': request.form.get('rojd_loc', ''),
                    'sem_poloj': request.form.get('sem_poloj', ''),
                    'rep_status': request.form.get('rep_status', ''),
                    'doc_lichn': request.form.get('doc_lichn', ''),
                    'n_doc_lichn': request.form.get('n_doc_lichn', ''),
                    'adres': request.form.get('adres', ''),
                    'tel': request.form.get('tel', ''),
                    'mail': request.form.get('mail', ''),
                    'rezerv': request.form.get('rezerv', ''),
                    'dop_info': request.form.get('dop_info', ''),
                    'children_data': request.form.get('children_data', ''),
                    'family_data': request.form.get('family_data', '')
                }
                print(f"DEBUG: form_data = {form_data}")  # Отладочный вывод
                return render_template('register.html', form_data=form_data)

        return render_template('register.html')

    # Страница поиска репатриантов
    @app.route('/search')
    @login_required
    def search():
        query = request.args.get('q', '')
        page = request.args.get('page', 1, type=int)

        # Получаем роль пользователя для определения порядка сортировки
        user_role = session.get('role', '')
        is_social_adaptation = (user_role == 'SOCIAL_ADAPTATION')

        # Получаем параметры расширенного поиска
        advanced_params = {
            'f': request.args.get('f', '').strip(),
            'i': request.args.get('i', '').strip(),
            'o': request.args.get('o', '').strip(),
            'f_hist': request.args.get('f_hist', '').strip(),
            'sex': request.args.get('sex', '').strip(),
            'date_r_from': request.args.get('date_r_from', '').strip(),
            'date_r_to': request.args.get('date_r_to', '').strip(),
            'kod': request.args.get('kod', '').strip(),
            'strana_proj': request.args.get('strana_proj', '').strip(),
            'from_loc': request.args.get('from_loc', '').strip(),
            'sem_poloj': request.args.get('sem_poloj', '').strip(),
            'rep_status_from': request.args.get('rep_status_from', '').strip(),
            'rep_status_to': request.args.get('rep_status_to', '').strip(),
            'rezerv': request.args.get('rezerv', '').strip(),
            'doc_lichn': request.args.get('doc_lichn', '').strip(),
            'n_doc_lichn': request.args.get('n_doc_lichn', '').strip(),
            'tel': request.args.get('tel', '').strip(),
            'mail': request.args.get('mail', '').strip(),
            'adres': request.args.get('adres', '').strip(),
            'rojd_loc': request.args.get('rojd_loc', '').strip(),
            'children_count': request.args.get('children_count', '').strip(),
            'dop_info': request.args.get('dop_info', '').strip(),
        }

        # Параметры поиска по жилищному отделу (только для HOUSING_DEPARTMENT и ADMIN)
        housing_params = {}
        if user_role == 'HOUSING_DEPARTMENT' or user_role == 'ADMIN':
            housing_params = {
                'category': request.args.get('housing_category', '').strip(),
                'received_housing': request.args.get('housing_received_housing', '').strip(),
                'housing_status': request.args.get('housing_status', '').strip(),  # Статус жилья (было housing_type)
                'address_city': request.args.get('housing_address_city', '').strip(),
                'address_street': request.args.get('housing_address_street', '').strip(),
                'address_house': request.args.get('housing_address_house', '').strip(),
                'address_apartment': request.args.get('housing_address_apartment', '').strip(),
                'has_warrant': request.args.get('housing_has_warrant', '').strip(),
                'repair_amount': request.args.get('housing_repair_amount', '').strip(),
                'protocol_number': request.args.get('housing_protocol_number', '').strip(),
                'notes': request.args.get('housing_notes', '').strip(),
                'created_at_from': request.args.get('housing_created_at_from', '').strip(),
                'created_at_to': request.args.get('housing_created_at_to', '').strip(),
            }

        # Проверяем, есть ли параметры расширенного поиска
        has_advanced_params = any(value for value in advanced_params.values()) or any(value for value in housing_params.values())

        # Функция для получения порядка сортировки в зависимости от роли
        def get_order_by():
            """Возвращает порядок сортировки: для SOCIAL_ADAPTATION сначала репатрианты со статусом"""
            if is_social_adaptation:
                # Сначала репатрианты со статусом (rep_status IS NOT NULL), потом остальные
                # Затем сортировка по id в порядке убывания
                return [
                    db.case(
                        [(Repatriant.rep_status.isnot(None), 0)],
                        else_=1
                    ),
                    Repatriant.id.desc()
                ]
            else:
                # Обычная сортировка по id в порядке убывания
                return [Repatriant.id.desc()]

        if has_advanced_params:
            # Расширенный поиск
            conditions = []

            # Личные данные (без учета регистра)
            if advanced_params['f']:
                conditions.append(Repatriant.f.op('~*')(rf'\y{advanced_params["f"]}\y'))
            if advanced_params['i']:
                conditions.append(Repatriant.i.op('~*')(rf'\y{advanced_params["i"]}\y'))
            if advanced_params['o']:
                conditions.append(Repatriant.o.op('~*')(rf'\y{advanced_params["o"]}\y'))
            if advanced_params['f_hist']:
                conditions.append(Repatriant.f_hist.op('~*')(rf'\y{advanced_params["f_hist"]}\y'))

            # Точные совпадения
            if advanced_params['sex']:
                conditions.append(Repatriant.sex == advanced_params['sex'])
            if advanced_params['kod']:
                kod_value = advanced_params['kod'].strip()
                # Точное совпадение кода (без учета регистра, но без подстановочных символов)
                conditions.append(db.func.upper(db.cast(Repatriant.kod, db.String)) == db.func.upper(kod_value))

            # Даты (интервалы)
            if advanced_params['date_r_from']:
                try:
                    date_r_from = datetime.strptime(advanced_params['date_r_from'], '%Y-%m-%d').date()
                    conditions.append(Repatriant.date_r >= date_r_from)
                except ValueError:
                    pass

            if advanced_params['date_r_to']:
                try:
                    date_r_to = datetime.strptime(advanced_params['date_r_to'], '%Y-%m-%d').date()
                    conditions.append(Repatriant.date_r <= date_r_to)
                except ValueError:
                    pass

            if advanced_params['rep_status_from']:
                try:
                    rep_status_from = datetime.strptime(advanced_params['rep_status_from'], '%Y-%m-%d').date()
                    conditions.append(Repatriant.rep_status >= rep_status_from)
                except ValueError:
                    pass

            if advanced_params['rep_status_to']:
                try:
                    rep_status_to = datetime.strptime(advanced_params['rep_status_to'], '%Y-%m-%d').date()
                    conditions.append(Repatriant.rep_status <= rep_status_to)
                except ValueError:
                    pass

            # Текстовые поля (без учета регистра)
            if advanced_params['strana_proj']:
                conditions.append(Repatriant.strana_proj.op('~*')(rf'\y{advanced_params["strana_proj"]}\y'))
            if advanced_params['from_loc']:
                conditions.append(Repatriant.from_loc.op('~*')(rf'\y{advanced_params["from_loc"]}\y'))
            if advanced_params['sem_poloj']:
                conditions.append(Repatriant.sem_poloj == advanced_params['sem_poloj'])
            if advanced_params['rezerv']:
                conditions.append(Repatriant.rezerv.op('~*')(rf'\y{advanced_params["rezerv"]}\y'))
            if advanced_params['doc_lichn']:
                conditions.append(Repatriant.doc_lichn.op('~*')(rf'\y{advanced_params["doc_lichn"]}\y'))
            if advanced_params['n_doc_lichn']:
                conditions.append(Repatriant.n_doc_lichn.op('~*')(rf'\y{advanced_params["n_doc_lichn"]}\y'))
            if advanced_params['tel']:
                conditions.append(Repatriant.tel.op('~*')(rf'\y{advanced_params["tel"]}\y'))
            if advanced_params['mail']:
                conditions.append(Repatriant.mail.op('~*')(rf'\y{advanced_params["mail"]}\y'))
            if advanced_params['adres']:
                conditions.append(Repatriant.adres.op('~*')(rf'\y{advanced_params["adres"]}\y'))
            if advanced_params['rojd_loc']:
                conditions.append(Repatriant.rojd_loc.op('~*')(rf'\y{advanced_params["rojd_loc"]}\y'))
            if advanced_params['dop_info']:
                conditions.append(Repatriant.dop_info.op('~*')(rf'\y{advanced_params["dop_info"]}\y'))

            # Создаем базовый запрос
            base_query = Repatriant.query

            # Фильтр по количеству детей (до 18 лет)
            if advanced_params['children_count']:
                try:
                    target_count = int(advanced_params['children_count'])
                    current_year = datetime.now().year

                    # Подзапрос для подсчета детей до 18 лет
                    # Учитываем, что god_r может содержать дату в формате "04.05.2001Г." или просто год
                    # Используем регулярное выражение PostgreSQL для извлечения 4-значного года из строки

                    # Извлекаем год из строки: используем regexp_replace для удаления всех нецифровых символов,
                    # затем берем последние 4 символа (год), или первые 4, если строка короткая
                    # Более безопасный подход: используем CASE WHEN для обработки ошибок преобразования
                    god_r_text = db.cast(Child.god_r, db.String)
                    # Удаляем все нецифровые символы, оставляем только цифры
                    digits_only = db.func.regexp_replace(god_r_text, r'[^0-9]', '', 'g')
                    # Берем последние 4 цифры (год) или все, если меньше 4
                    year_str = db.func.right(digits_only, 4)
                    # Преобразуем в число, используя CASE WHEN для безопасного преобразования
                    year_extract = db.case(
                        [
                            (db.func.length(year_str) == 4, db.cast(year_str, db.Integer))
                        ],
                        else_=None
                    )

                    children_subquery = db.session.query(
                        Child.list_id,
                        db.func.count(Child.id_child).label('children_count')
                    ).filter(
                        # Проверяем, что год рождения указан и ребенок младше 18 лет
                        db.and_(
                            Child.god_r.isnot(None),
                            Child.god_r != '',
                            # Извлекаем год и проверяем, что он валидный
                            year_extract.isnot(None),
                            year_extract >= (current_year - 17),  # От 0 до 17 лет включительно
                            year_extract <= current_year,
                            # Дополнительная проверка: год должен быть разумным (не раньше 1900)
                            year_extract >= 1900
                        )
                    ).group_by(Child.list_id).having(
                        db.func.count(Child.id_child) == target_count
                    ).subquery()

                    # Используем join для фильтрации по количеству детей
                    base_query = base_query.join(
                        children_subquery,
                        Repatriant.id == children_subquery.c.list_id
                    )
                except (ValueError, TypeError) as e:
                    # Если не удалось преобразовать в число, игнорируем этот фильтр
                    print(f"Ошибка при фильтрации по количеству детей: {e}")
                    pass

            # Фильтрация по записям жилищного отдела (только для HOUSING_DEPARTMENT и ADMIN)
            if (user_role == 'HOUSING_DEPARTMENT' or user_role == 'ADMIN') and any(value for value in housing_params.values()):
                housing_conditions = [HousingDepartmentRecord.is_deleted == False]

                # Текстовые поля (без учета регистра)
                if housing_params['category']:
                    housing_conditions.append(HousingDepartmentRecord.category.op('~*')(rf'\y{housing_params["category"]}\y'))
                if housing_params['protocol_number']:
                    housing_conditions.append(HousingDepartmentRecord.protocol_number.op('~*')(rf'\y{housing_params["protocol_number"]}\y'))
                if housing_params['notes']:
                    housing_conditions.append(HousingDepartmentRecord.notes.op('~*')(rf'\y{housing_params["notes"]}\y'))

                # Булевы поля
                if housing_params['received_housing']:
                    housing_conditions.append(HousingDepartmentRecord.received_housing == (housing_params['received_housing'] == 'true'))
                if housing_params['has_warrant']:
                    housing_conditions.append(HousingDepartmentRecord.has_warrant == (housing_params['has_warrant'] == 'true'))

                # Статус жилья (используем housing_acquisition, где хранятся значения: ведомственное, выкуплено, передано)
                if housing_params['housing_status']:
                    housing_conditions.append(HousingDepartmentRecord.housing_acquisition == housing_params['housing_status'])

                # Поиск по адресу (разбит на части: город, улица, дом, квартира)
                # Адрес в базе хранится как "Город, Улица, Дом, Квартира"
                address_parts = []
                if housing_params['address_city']:
                    address_parts.append((0, housing_params['address_city']))  # Первая часть - город
                if housing_params['address_street']:
                    address_parts.append((1, housing_params['address_street']))  # Вторая часть - улица
                if housing_params['address_house']:
                    address_parts.append((2, housing_params['address_house']))  # Третья часть - дом
                if housing_params['address_apartment']:
                    address_parts.append((3, housing_params['address_apartment']))  # Четвертая часть - квартира

                if address_parts:
                    # Для каждого указанного компонента адреса проверяем соответствующую часть
                    for part_index, part_value in address_parts:
                        # Используем split_part для извлечения нужной части адреса (индекс начинается с 1)
                        # Ищем без учета регистра
                        housing_conditions.append(
                            db.func.split_part(HousingDepartmentRecord.address, ', ', part_index + 1).op('~*')(rf'\y{part_value}\y')
                        )

                # Числовое поле
                if housing_params['repair_amount']:
                    try:
                        repair_amount = float(housing_params['repair_amount'])
                        housing_conditions.append(HousingDepartmentRecord.repair_amount == repair_amount)
                    except (ValueError, TypeError):
                        pass

                # Даты
                if housing_params['created_at_from']:
                    try:
                        created_at_from = datetime.strptime(housing_params['created_at_from'], '%Y-%m-%d')
                        housing_conditions.append(db.cast(HousingDepartmentRecord.created_at, db.Date) >= created_at_from.date())
                    except ValueError:
                        pass

                if housing_params['created_at_to']:
                    try:
                        created_at_to = datetime.strptime(housing_params['created_at_to'], '%Y-%m-%d')
                        housing_conditions.append(db.cast(HousingDepartmentRecord.created_at, db.Date) <= created_at_to.date())
                    except ValueError:
                        pass

                # Создаем подзапрос для получения ID репатриантов с подходящими записями
                housing_subquery = db.session.query(
                    HousingDepartmentRecord.repatriant_id
                ).filter(
                    db.and_(*housing_conditions)
                ).distinct().subquery()

                # Используем join для фильтрации по записям жилищного отдела
                base_query = base_query.join(
                    housing_subquery,
                    Repatriant.id == housing_subquery.c.repatriant_id
                )

            # Применяем остальные условия
            if conditions:
                base_query = base_query.filter(db.and_(*conditions))

            # Выполняем поиск
            repatriants = base_query.order_by(*get_order_by()).paginate(page=page, per_page=20, error_out=False)

        elif query:
            # Обычный поиск по ФИО и исторической фамилии (без учета регистра)
            search_words = query.strip().split()

            if len(search_words) == 1:
                # Поиск по одному слову
                word = search_words[0]
                word_pattern = rf'\y{word}\y'
                repatriants = Repatriant.query.filter(
                    db.or_(
                        Repatriant.f.op('~*')(word_pattern),
                        Repatriant.i.op('~*')(word_pattern),
                        Repatriant.o.op('~*')(word_pattern),
                        Repatriant.f_hist.op('~*')(word_pattern)  # Добавлена историческая фамилия
                    )
                ).order_by(*get_order_by()).paginate(page=page, per_page=20, error_out=False)
            else:
                # Поиск по нескольким словам - ищем записи, где все слова найдены в ФИО или исторической фамилии
                conditions = []
                for word in search_words:
                    word_pattern = rf'\y{word}\y'
                    word_condition = db.or_(
                        Repatriant.f.op('~*')(word_pattern),
                        Repatriant.i.op('~*')(word_pattern),
                        Repatriant.o.op('~*')(word_pattern),
                        Repatriant.f_hist.op('~*')(word_pattern)  # Добавлена историческая фамилия
                    )
                    conditions.append(word_condition)

                # Все условия должны выполняться одновременно (AND)
                repatriants = Repatriant.query.filter(
                    db.and_(*conditions)
                ).order_by(*get_order_by()).paginate(page=page, per_page=20, error_out=False)
        else:
            # Показать всех репатриантов
            repatriants = Repatriant.query.order_by(*get_order_by()).paginate(page=page, per_page=20, error_out=False)

        # Для жилищного отдела проверяем наличие записей для каждого репатрианта
        housing_records_map = {}
        if user_role == 'HOUSING_DEPARTMENT' or user_role == 'ADMIN':
            if query or has_advanced_params:
                # Получаем ID всех найденных репатриантов
                repatriant_ids = [r.id for r in repatriants.items]
                if repatriant_ids:
                    # Проверяем наличие записей жилищного отдела
                    housing_records = HousingDepartmentRecord.query.filter(
                        HousingDepartmentRecord.repatriant_id.in_(repatriant_ids),
                        HousingDepartmentRecord.is_deleted == False
                    ).all()
                    # Создаем словарь: repatriant_id -> True/False
                    for record in housing_records:
                        housing_records_map[record.repatriant_id] = True

        # Для жилищного отдела проверяем наличие записей для каждого репатрианта
        housing_records_map = {}
        if user_role == 'HOUSING_DEPARTMENT' or user_role == 'ADMIN':
            if query or has_advanced_params:
                # Получаем ID всех найденных репатриантов
                repatriant_ids = [r.id for r in repatriants.items]
                if repatriant_ids:
                    # Проверяем наличие записей жилищного отдела
                    housing_records = HousingDepartmentRecord.query.filter(
                        HousingDepartmentRecord.repatriant_id.in_(repatriant_ids),
                        HousingDepartmentRecord.is_deleted == False
                    ).all()
                    # Создаем словарь: repatriant_id -> True/False
                    for record in housing_records:
                        housing_records_map[record.repatriant_id] = True
            else:
                # Если нет поиска, проверяем для всех репатриантов на странице
                repatriant_ids = [r.id for r in repatriants.items]
                if repatriant_ids:
                    housing_records = HousingDepartmentRecord.query.filter(
                        HousingDepartmentRecord.repatriant_id.in_(repatriant_ids),
                        HousingDepartmentRecord.is_deleted == False
                    ).all()
                    for record in housing_records:
                        housing_records_map[record.repatriant_id] = True

        return render_template('search.html', 
                             repatriants=repatriants, 
                             query=query,
                             advanced_params=advanced_params,
                             housing_params=housing_params,
                             user_role=user_role,
                             housing_records_map=housing_records_map)

    # Маршрут для предварительной загрузки PDF
    @app.route('/upload_pdf_preview', methods=['POST'])
    @login_required
    def upload_pdf_preview():
        """Предварительная загрузка PDF для просмотра"""
        try:
            if 'documents' not in request.files:
                return jsonify({'error': 'PDF файл не найден'}), 400

            documents_file = request.files['documents']
            if not documents_file or not documents_file.filename:
                return jsonify({'error': 'Файл не выбран'}), 400

            # Проверяем расширение
            if not allowed_file(documents_file.filename):
                return jsonify({'error': 'Разрешены только PDF файлы'}), 400

            # Сохраняем файл во временную папку
            temp_filename = f"temp_{uuid.uuid4().hex[:8]}.pdf"
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp')
            os.makedirs(temp_path, exist_ok=True)

            full_path = os.path.join(temp_path, temp_filename)
            documents_file.save(full_path)

            # Возвращаем путь к временному файлу
            return jsonify({
                'success': True, 
                'temp_path': f'temp/{temp_filename}',
                'filename': documents_file.filename
            })

        except Exception as e:
            return jsonify({'error': f'Ошибка загрузки: {str(e)}'}), 500

    # Маршрут для сохранения вырезанной аватарки
    @app.route('/save_avatar', methods=['POST'])
    @login_required
    def save_avatar():
        """Сохраняет вырезанную аватарку"""
        try:
            if 'avatar' not in request.files:
                return jsonify({'error': 'Файл аватарки не найден'}), 400

            avatar_file = request.files['avatar']
            repatriant_id = request.form.get('repatriant_id')

            if not repatriant_id:
                return jsonify({'error': 'ID репатрианта не указан'}), 400

            # Получаем репатрианта
            repatriant = Repatriant.query.get_or_404(repatriant_id)

            # Удаляем старую аватарку если есть
            if repatriant.avatar_path:
                delete_file(repatriant.avatar_path)

            # Сохраняем новую аватарку
            avatar_path = save_file(avatar_file, 'avatars', f'avatar_{repatriant_id}')

            if avatar_path:
                repatriant.avatar_path = avatar_path
                db.session.commit()

                # Логируем действие
                log_user_action(f'Вырезана аватарка для репатрианта {repatriant.f} {repatriant.i} {repatriant.o}', repatriant_id)

                return jsonify({
                    'success': True, 
                    'message': 'Аватарка успешно сохранена',
                    'avatar_url': url_for('uploaded_file', filename=avatar_path)
                })
            else:
                return jsonify({'error': 'Ошибка сохранения файла'}), 500

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Ошибка: {str(e)}'}), 500

    # Маршрут для отображения загруженных файлов
    @app.route('/uploads/<path:filename>')
    @login_required
    def uploaded_file(filename):
        """Отображает загруженные файлы"""
        print(f"Запрос файла: {filename}")

        # Если это файл из новой системы (documents/ или avatars/)
        if filename.startswith('documents/') or filename.startswith('avatars/'):
            folder_name = filename.split('/')[0]  # documents или avatars
            file_name = filename.split('/')[1]    # имя файла

            print(f"Ищем файл: {file_name} в папке: {folder_name}")

            # Ищем файл на всех дисках
            for disk in app.config['STORAGE_DISKS']:
                file_path = os.path.join(disk['path'], file_name)
                print(f"Проверяем путь: {file_path}")
                if os.path.exists(file_path):
                    print(f"Файл найден на {disk['name']}: {file_path}")
                    return send_from_directory(disk['path'], file_name)

            # Если файл не найден на дисках, возвращаем ошибку
            print(f"Файл не найден на дисках: {file_name}")
            return "Файл не найден", 404
        else:
            # Старые файлы из папки uploads
            print(f"Ищем в старой папке: {app.config['UPLOAD_FOLDER']}/{filename}")
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Маршрут для просмотра статистики дисков
    @app.route('/admin/disk-stats')
    @admin_required
    def disk_stats():
        """Показывает статистику использования дисков"""
        import shutil

        disk_stats = []
        for disk in app.config['STORAGE_DISKS']:
            try:
                total, used, free = shutil.disk_usage(disk['path'])
                total_gb = total // (1024**3)
                used_gb = used // (1024**3)
                free_gb = free // (1024**3)
                usage_percent = (used / total) * 100

                disk_stats.append({
                    'name': disk['name'],
                    'path': disk['path'],
                    'total_gb': total_gb,
                    'used_gb': used_gb,
                    'free_gb': free_gb,
                    'usage_percent': round(usage_percent, 1)
                })
            except Exception as e:
                disk_stats.append({
                    'name': disk['name'],
                    'path': disk['path'],
                    'error': str(e)
                })

        return render_template('disk_stats.html', disk_stats=disk_stats)

    # Просмотр детальной информации о репатрианте
    @app.route('/view/<int:id>')
    @login_required
    def view_repatriant(id):
        repatriant = Repatriant.query.get_or_404(id)
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        # Получаем историю действий для этого репатрианта (только для админов)
        action_history = []
        if session.get('role') == 'ADMIN':
            action_history = db.session.execute("""
                SELECT "USER_NAME", "DATE_IZM", "TIME_IZM"
                FROM "LOG" 
                WHERE "LIST_ID" = :repatriant_id
                ORDER BY "ID_LOG" ASC
            """, {'repatriant_id': id}).fetchall()

        return render_template('view.html', 
                             repatriant=repatriant, 
                             children=children, 
                             family_members=family_members,
                             action_history=action_history)

    # Генерация заполненной формы заявления
    @app.route('/generate_form/<int:id>')
    @app.route('/generate_form/<int:id>/<form_type>')
    @login_required
    def generate_form(id, form_type='enhanced'):
        """Генерирует заполненную форму заявления для репатрианта

        Args:
            id: ID репатрианта
            form_type: тип формы ('enhanced' - улучшенная, 'standard' - стандартная)
        """
        try:
            repatriant = Repatriant.query.get_or_404(id)
            children = Child.query.filter_by(list_id=id).all()
            family_members = FamilyMember.query.filter_by(list_id=id).all()

            # Выбираем форму
            if form_type == 'enhanced':
                from fill_enhanced_form import fill_enhanced_application_form
                template_path = 'application_form_enhanced.docx'
                fill_func = fill_enhanced_application_form
            else:
                from fill_application_form import fill_application_form
                template_path = 'application_form.docx'
                fill_func = fill_application_form

            if not os.path.exists(template_path):
                flash(f'Шаблон формы не найден: {template_path}', 'error')
                return redirect(url_for('view_repatriant', id=id))

            # Создаем временный файл для заполненной формы
            import tempfile
            temp_dir = tempfile.gettempdir()
            output_filename = f'Заявление_{repatriant.f}_{repatriant.i}_{repatriant.id}.docx'
            output_path = os.path.join(temp_dir, output_filename)

            # Заполняем форму
            fill_func(
                repatriant=repatriant,
                children=children,
                family_members=family_members,
                template_path=template_path,
                output_path=output_path
            )

            # Отправляем файл пользователю
            return send_file(
                output_path,
                as_attachment=True,
                download_name=output_filename,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )

        except Exception as e:
            flash(f'Ошибка при генерации формы: {str(e)}', 'error')
            import traceback
            print(traceback.format_exc())
            return redirect(url_for('view_repatriant', id=id))

    # Просмотр для социально адаптационного отдела
    @app.route('/socview/<int:id>')
    @login_required
    def socview_repatriant(id):
        # Проверяем, что пользователь имеет роль SOCIAL_ADAPTATION или ADMIN
        if session.get('role') not in ['SOCIAL_ADAPTATION', 'ADMIN']:
            flash('У вас нет доступа к этой странице', 'error')
            return redirect(url_for('search'))

        repatriant = Repatriant.query.get_or_404(id)
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        return render_template('socview.html', 
                             repatriant=repatriant, 
                             children=children, 
                             family_members=family_members)

    # Просмотр для жилищного отдела
    @app.route('/view-housing/<int:id>')
    @login_required
    def view_housing_repatriant(id):
        # Проверяем, что пользователь имеет роль HOUSING_DEPARTMENT или ADMIN
        if session.get('role') not in ['HOUSING_DEPARTMENT', 'ADMIN']:
            flash('У вас нет доступа к этой странице', 'error')
            return redirect(url_for('search'))

        repatriant = Repatriant.query.get_or_404(id)
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        return render_template('view_housing.html', 
                             repatriant=repatriant, 
                             children=children, 
                             family_members=family_members)

    @app.route('/houseregistration/<int:id>')
    @login_required
    def houseregistration_repatriant(id):
        # Проверяем, что пользователь имеет роль HOUSING_DEPARTMENT или ADMIN
        if session.get('role') not in ['HOUSING_DEPARTMENT', 'ADMIN']:
            flash('У вас нет доступа к этой странице', 'error')
            return redirect(url_for('search'))

        repatriant = Repatriant.query.get_or_404(id)
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        return render_template('houseregistration.html', 
                             repatriant=repatriant, 
                             children=children, 
                             family_members=family_members)

    @app.route('/edit_housing/<int:id>')
    @login_required
    def edit_housing_repatriant(id):
        # Проверяем, что пользователь имеет роль HOUSING_DEPARTMENT или ADMIN
        if session.get('role') not in ['HOUSING_DEPARTMENT', 'ADMIN']:
            flash('У вас нет доступа к этой странице', 'error')
            return redirect(url_for('search'))

        repatriant = Repatriant.query.get_or_404(id)
        children = Child.query.filter_by(list_id=id).all()
        family_members = FamilyMember.query.filter_by(list_id=id).all()

        # Получаем последнюю запись жилищного отдела для этого репатрианта
        housing_record = HousingDepartmentRecord.query.filter_by(
            repatriant_id=id,
            is_deleted=False
        ).order_by(HousingDepartmentRecord.created_at.desc()).first()

        if not housing_record:
            flash('Запись жилищного отдела не найдена', 'error')
            return redirect(url_for('search'))

        return render_template('edit_housing.html', 
                             repatriant=repatriant, 
                             children=children, 
                             family_members=family_members,
                             housing_record=housing_record)

    @app.route('/housing-queue')
    @login_required
    def housing_queue():
        # Проверяем, что пользователь имеет роль HOUSING_DEPARTMENT или ADMIN
        if session.get('role') not in ['HOUSING_DEPARTMENT', 'ADMIN']:
            flash('У вас нет доступа к этой странице', 'error')
            return redirect(url_for('search'))

        return render_template('housing_queue.html')

