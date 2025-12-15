from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory, send_file, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, event
from datetime import datetime, timedelta
import os
import json
import uuid
import shutil
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:123@localhost/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Конфигурация для равномерного заполнения дисков
app.config['STORAGE_DISKS'] = [
    {'path': 'D:\\repatriants_files', 'priority': 1, 'name': 'Диск D'},
    {'path': 'E:\\repatriants_files', 'priority': 2, 'name': 'Диск E'}
]
app.config['BACKUP_DISK'] = 'F:\\repatriants_backup'  # Резервный диск

# Старая папка для совместимости (временные файлы)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB для сканов документов

db = SQLAlchemy(app)

# Создаем папки на дисках при запуске
def create_disk_folders():
    """Создает необходимые папки на дисках"""
    folders_to_create = [
        app.config['BACKUP_DISK'],  # Резервный диск
        os.path.join(app.config['UPLOAD_FOLDER'], 'temp'),  # Временные файлы
        os.path.join(app.config['UPLOAD_FOLDER'], 'documents'),  # Для совместимости
        os.path.join(app.config['UPLOAD_FOLDER'], 'avatars')   # Для совместимости
    ]
    
    # Добавляем папки для каждого диска хранения
    for disk in app.config['STORAGE_DISKS']:
        folders_to_create.append(disk['path'])
    
    for folder in folders_to_create:
        try:
            os.makedirs(folder, exist_ok=True)
            print(f"✓ Папка создана/проверена: {folder}")
        except Exception as e:
            print(f"✗ Ошибка создания папки {folder}: {e}")

# Создаем папки при запуске
create_disk_folders()

# Функция для выбора диска с наименьшим заполнением
def normalize_nationality_value(value):
    """Нормализует значение национальности (преобразует женский род в мужской)
    Согласно стандартизации из normalize_nationality.py
    """
    if not value:
        return value
    
    value_upper = value.strip().upper()
    
    # Маппинг женского рода на мужской (стандартизированные значения)
    nationality_mapping = {
        'АБХАЗКА': 'АБХАЗ',
        'АБАЗИНКА': 'АБАЗИН',
        'КАБАРДИНКА': 'КАБАРДИНЕЦ',
        'АДЫГЕЙКА': 'АДЫГ',
        'УБЫХКА': 'УБЫХ',
    }
    
    # Если значение есть в маппинге, возвращаем стандартизированное
    if value_upper in nationality_mapping:
        return nationality_mapping[value_upper]
    
    # Если значение уже стандартизировано, возвращаем как есть
    standard_values = ['АБХАЗ', 'АБАЗИН', 'КАБАРДИНЕЦ', 'АДЫГ', 'УБЫХ']
    if value_upper in standard_values:
        return value_upper
    
    # Для всех остальных значений (включая "Другое") возвращаем как есть
    return value.strip()

def get_best_disk():
    """Выбирает диск с наименьшим заполнением"""
    import shutil
    
    best_disk = None
    max_free_space = 0
    
    for disk in app.config['STORAGE_DISKS']:
        try:
            # Получаем статистику диска
            total, used, free = shutil.disk_usage(disk['path'])
            free_gb = free // (1024**3)  # Свободное место в ГБ
            
            print(f"{disk['name']}: {free_gb} ГБ свободно")
            
            if free_gb > max_free_space:
                max_free_space = free_gb
                best_disk = disk
                
        except Exception as e:
            print(f"Ошибка проверки диска {disk['name']}: {e}")
            continue
    
    if best_disk:
        print(f"Выбран диск: {best_disk['name']} ({max_free_space} ГБ свободно)")
        return best_disk['path']
    else:
        # Если все диски недоступны, используем первый
        print("Все диски недоступны, используем первый диск")
        return app.config['STORAGE_DISKS'][0]['path']

# Модель для основной таблицы репатриантов
class Repatriant(db.Model):
    __tablename__ = 'MAIN'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    kod = db.Column('KOD', db.String(50))  # Код личного дела (архивный номер) - может содержать буквы и цифры
    f_hist = db.Column('F_HIST', db.String(100))
    f = db.Column('F', db.String(100))
    i = db.Column('I', db.String(100))
    o = db.Column('O', db.String(100))
    strana_proj = db.Column('STRANA_PROJ', db.String(100))
    from_loc = db.Column('FROM_LOC', db.String(100))
    reshenie_komissii = db.Column('RESHENIE_KOMISSII', db.Boolean, default=False, nullable=False)  # Решение комиссии
    date_r = db.Column('DATE_R', db.Date)
    file = db.Column('FILE', db.LargeBinary)
    f_name = db.Column('F_NAME', db.String(255))
    sex = db.Column('SEX', db.String(10))
    date_death = db.Column('DATE_DEATH', db.Date)
    rojd_loc = db.Column('ROJD_LOC', db.String(255))
    sem_poloj = db.Column('SEM_POLOJ', db.String(100))
    rep_status = db.Column('REP_STATUS', db.Date)
    rep_status_reg = db.Column('REP_STATUS_REG', db.Date)
    date_registration = db.Column('DATE_REGISTRATION', db.Date)  # Дата регистрации репатрианта
    dop_info = db.Column('DOP_INFO', db.String(255))
    photo = db.Column('PHOTO', db.LargeBinary)
    avatar_path = db.Column('AVATAR_PATH', db.String(500))  # Путь к аватарке
    documents_path = db.Column('DOCUMENTS_PATH', db.String(500))  # Путь к PDF документам
    doc_lichn = db.Column('DOC_LICHN', db.String(100))
    n_doc_lichn = db.Column('N_DOC_LICHN', db.String(255))
    adres = db.Column('ADRES', db.String(255))
    tel = db.Column('TEL', db.String(50))
    mail = db.Column('MAIL', db.String(100))
    n_doc_jil = db.Column('N_DOC_JIL', db.String(255))
    date_doc_jil = db.Column('DATE_DOC_JIL', db.Date)
    dop_jil = db.Column('DOP_JIL', db.String(255))
    syt_jil = db.Column('SYT_JIL', db.String(255))
    note_jil = db.Column('NOTE_JIL', db.String(255))
    sost_sem_jil = db.Column('SOST_SEM_JIL', db.String(255))
    isp_jil = db.Column('ISP_JIL', db.String(100))
    gde_naiti_jil = db.Column('GDE_NAITI_JIL', db.String(255))
    adres_jil = db.Column('ADRES_JIL', db.String(255))
    rezerv = db.Column('REZERV', db.String(100))
    file_jil = db.Column('FILE_JIL', db.LargeBinary)
    f_name_jil = db.Column('F_NAME_JIL', db.String(255))

    def __repr__(self):
        return f'<Repatriant {self.f} {self.i} {self.o}>'

    # Модель для таблицы детей (только СЫН и ДОЧЬ)
class Child(db.Model):
    __tablename__ = 'CHILDREN'
    
    id_child = db.Column('ID_CHILD', db.Integer, primary_key=True)
    list_id = db.Column('LIST_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    step_rod = db.Column('STEP_ROD', db.String(50))  # Только 'СЫН' или 'ДОЧЬ'
    fio = db.Column('FIO', db.String(255))
    god_r = db.Column('GOD_R', db.String(10))
    mesto_r = db.Column('MESTO_R', db.String(255))
    grajdanstvo = db.Column('GRAJDANSTVO', db.String(100))  # Гражданство
    nacionalnost = db.Column('NACIONALNOST', db.String(100))  # Национальность
    lives_with_parent = db.Column('LIVES_WITH_PARENT', db.Boolean, default=False)  # Проживает с родителем (по умолчанию НЕ проживает)
    
    # Связь с основной таблицей
    repatriant = db.relationship('Repatriant', backref='children')

    def __repr__(self):
        return f'<Child {self.fio}>'

    # Модель для таблицы семьи (все родственники кроме детей)
class FamilyMember(db.Model):
    __tablename__ = 'FAMILY'
    
    id_family = db.Column('ID_FAMILY', db.Integer, primary_key=True)
    list_id = db.Column('LIST_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    step_rod = db.Column('STEP_ROD', db.String(50))  # Все кроме 'СЫН' и 'ДОЧЬ'
    fio = db.Column('FIO', db.String(255))
    god_r = db.Column('GOD_R', db.Integer)
    grajdanstvo = db.Column('GRAJDANSTVO', db.String(100))
    nacionalnost = db.Column('NACIONALNOST', db.String(100))
    adres = db.Column('ADRES', db.String(255))
    lives_with_parent = db.Column('LIVES_WITH_PARENT', db.Boolean, default=False)  # Проживает с репатриантом (по умолчанию НЕ проживает)
    
    # Связь с основной таблицей
    repatriant = db.relationship('Repatriant', backref='family_members')

    def __repr__(self):
        return f'<FamilyMember {self.fio}>'

# Модель для таблицы пользователей
class User(db.Model):
    __tablename__ = 'USERS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    username = db.Column('USERNAME', db.String(50), unique=True, nullable=False)
    password_hash = db.Column('PASSWORD_HASH', db.String(255), nullable=False)
    full_name = db.Column('FULL_NAME', db.String(100), nullable=False)
    role = db.Column('ROLE', db.String(20), nullable=False, default='USER')
    is_active = db.Column('IS_ACTIVE', db.Boolean, nullable=False, default=True)
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    last_login = db.Column('LAST_LOGIN', db.DateTime)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def check_password(self, password):
        """Проверяет пароль"""
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)
    
    def set_password(self, password):
        """Устанавливает пароль"""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

# Модели для социально адаптационного отдела
class HousingRecord(db.Model):
    """Модель для записей об аренде жилья"""
    __tablename__ = 'HOUSING_RECORDS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    contract_number = db.Column('CONTRACT_NUMBER', db.String(100))
    address = db.Column('ADDRESS', db.String(500), nullable=False)
    start_date = db.Column('START_DATE', db.Date, nullable=False)
    end_date = db.Column('END_DATE', db.Date)
    cost = db.Column('COST', db.Numeric(10, 2))
    documents_path = db.Column('DOCUMENTS_PATH', db.String(1000))  # JSON массив путей к файлам
    notes = db.Column('NOTES', db.Text)
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_deleted = db.Column('IS_DELETED', db.Boolean, default=False, nullable=False)
    deleted_at = db.Column('DELETED_AT', db.DateTime)
    deleted_by = db.Column('DELETED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'contract_number': self.contract_number,
            'address': self.address,
            'start_date': self.start_date.strftime('%Y-%m-%d') if self.start_date else None,
            'end_date': self.end_date.strftime('%Y-%m-%d') if self.end_date else None,
            'cost': float(self.cost) if self.cost else None,
            'documents': json.loads(self.documents_path) if self.documents_path else [],
            'notes': self.notes,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'is_deleted': getattr(self, 'is_deleted', False),
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(self, 'deleted_at') and self.deleted_at else None
        }

class SocialHelpRecord(db.Model):
    """Модель для записей о социальной помощи"""
    __tablename__ = 'SOCIAL_HELP_RECORDS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    help_type = db.Column('HELP_TYPE', db.String(100), nullable=False)
    custom_help_type = db.Column('CUSTOM_HELP_TYPE', db.String(200))
    responsible = db.Column('RESPONSIBLE', db.String(200))
    help_date = db.Column('HELP_DATE', db.Date, nullable=False)
    amount = db.Column('AMOUNT', db.String(100))
    documents_path = db.Column('DOCUMENTS_PATH', db.String(1000))  # JSON массив путей к файлам
    description = db.Column('DESCRIPTION', db.Text)
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_deleted = db.Column('IS_DELETED', db.Boolean, default=False, nullable=False)
    deleted_at = db.Column('DELETED_AT', db.DateTime)
    deleted_by = db.Column('DELETED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'help_type': self.help_type,
            'custom_help_type': self.custom_help_type,
            'responsible': self.responsible,
            'help_date': self.help_date.strftime('%Y-%m-%d') if self.help_date else None,
            'amount': self.amount,
            'documents': json.loads(self.documents_path) if self.documents_path else [],
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'is_deleted': getattr(self, 'is_deleted', False),
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(self, 'deleted_at') and self.deleted_at else None
        }

class EventRecord(db.Model):
    """Модель для записей о мероприятиях"""
    __tablename__ = 'EVENT_RECORDS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    event_name = db.Column('EVENT_NAME', db.String(500), nullable=False)
    event_start_date = db.Column('EVENT_START_DATE', db.Date, nullable=False)
    event_end_date = db.Column('EVENT_END_DATE', db.Date)
    event_location = db.Column('EVENT_LOCATION', db.String(500))
    event_type = db.Column('EVENT_TYPE', db.String(100))
    event_amount = db.Column('EVENT_AMOUNT', db.Numeric(10, 2))
    description = db.Column('DESCRIPTION', db.Text)
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_deleted = db.Column('IS_DELETED', db.Boolean, default=False, nullable=False)
    deleted_at = db.Column('DELETED_AT', db.DateTime)
    deleted_by = db.Column('DELETED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'event_name': self.event_name,
            'event_start_date': self.event_start_date.strftime('%Y-%m-%d') if self.event_start_date else None,
            'event_end_date': self.event_end_date.strftime('%Y-%m-%d') if self.event_end_date else None,
            'event_location': self.event_location,
            'event_type': self.event_type,
            'event_amount': float(self.event_amount) if self.event_amount else None,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'is_deleted': getattr(self, 'is_deleted', False),
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(self, 'deleted_at') and self.deleted_at else None
        }

class OtherRecord(db.Model):
    """Модель для прочих записей"""
    __tablename__ = 'OTHER_RECORDS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    title = db.Column('TITLE', db.String(500), nullable=False)
    record_date = db.Column('RECORD_DATE', db.Date, nullable=False)
    category = db.Column('CATEGORY', db.String(200))
    content = db.Column('CONTENT', db.Text, nullable=False)
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_deleted = db.Column('IS_DELETED', db.Boolean, default=False, nullable=False)
    deleted_at = db.Column('DELETED_AT', db.DateTime)
    deleted_by = db.Column('DELETED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'record_date': self.record_date.strftime('%Y-%m-%d') if self.record_date else None,
            'category': self.category,
            'content': self.content,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'is_deleted': getattr(self, 'is_deleted', False),
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(self, 'deleted_at') and self.deleted_at else None
        }

# Модели для жилищного отдела
class HousingDepartmentRecord(db.Model):
    """Модель для записей жилищного отдела"""
    __tablename__ = 'HOUSING_DEPARTMENT_RECORDS'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False)
    category = db.Column('CATEGORY', db.String(200))  # Категория
    received_housing = db.Column('RECEIVED_HOUSING', db.Boolean)  # Получил жилье (да/нет)
    housing_type = db.Column('HOUSING_TYPE', db.String(100))  # ведомственное/частное
    housing_acquisition = db.Column('HOUSING_ACQUISITION', db.String(200))  # Выкуплено/Передано
    address = db.Column('ADDRESS', db.String(500))  # Адрес
    # family_composition удален - данные хранятся только в таблицах CHILDREN и FAMILY
    has_warrant = db.Column('HAS_WARRANT', db.Boolean)  # Ордер (да/нет)
    repair_amount = db.Column('REPAIR_AMOUNT', db.Numeric(10, 2))  # Ремонт жилья (сумма)
    documents_path = db.Column('DOCUMENTS_PATH', db.String(1000))  # JSON массив путей к файлам
    notes = db.Column('NOTES', db.Text)
    protocol_number = db.Column('PROTOCOL_NUMBER', db.String(200))  # Номер протокола
    created_at = db.Column('CREATED_AT', db.DateTime, default=datetime.utcnow)
    created_by = db.Column('CREATED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_deleted = db.Column('IS_DELETED', db.Boolean, default=False, nullable=False)
    deleted_at = db.Column('DELETED_AT', db.DateTime)
    deleted_by = db.Column('DELETED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    
    def _parse_documents(self):
        """Парсит документы, поддерживая старый формат (массив строк) и новый (массив объектов)"""
        if not self.documents_path:
            return []
        try:
            parsed_docs = json.loads(self.documents_path)
            if not parsed_docs:
                return []
            # Если это массив строк (старый формат), преобразуем в новый формат
            if isinstance(parsed_docs[0], str):
                return [{'path': doc, 'name': ''} for doc in parsed_docs]
            # Если это уже массив объектов (новый формат)
            return parsed_docs
        except (json.JSONDecodeError, TypeError, IndexError):
            return []
    
    def to_dict(self):
        return {
            'id': self.id,
            'repatriant_id': self.repatriant_id,
            'category': self.category,
            'received_housing': self.received_housing,
            'housing_type': self.housing_type,
            'housing_acquisition': self.housing_acquisition,
            'address': self.address,
            # 'family_composition' удален из базы данных - данные в CHILDREN и FAMILY
            'has_warrant': self.has_warrant,
            'repair_amount': float(self.repair_amount) if self.repair_amount else None,
            'documents': self._parse_documents(),
            'notes': self.notes,
            'protocol_number': self.protocol_number,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'is_deleted': self.is_deleted
        }

class HousingQueue(db.Model):
    """Модель для очереди жилищного отдела"""
    __tablename__ = 'HOUSING_QUEUE'
    
    id = db.Column('ID', db.Integer, primary_key=True, autoincrement=True)
    repatriant_id = db.Column('REPATRIANT_ID', db.Integer, db.ForeignKey('MAIN.ID'), nullable=False, unique=True)
    # Балльная система
    has_children = db.Column('HAS_CHILDREN', db.Boolean, default=False)  # Есть дети
    has_work = db.Column('HAS_WORK', db.Boolean, default=False)  # Есть работа
    has_law_violations = db.Column('HAS_LAW_VIOLATIONS', db.Boolean, default=False)  # Есть нарушения закона
    total_score = db.Column('TOTAL_SCORE', db.Integer, default=0)  # Общий балл
    queue_position = db.Column('QUEUE_POSITION', db.Integer)  # Позиция в очереди
    added_at = db.Column('ADDED_AT', db.DateTime, default=datetime.utcnow)  # Время добавления
    added_by = db.Column('ADDED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    removed_at = db.Column('REMOVED_AT', db.DateTime)
    removed_by = db.Column('REMOVED_BY', db.Integer, db.ForeignKey('USERS.ID'))
    is_active = db.Column('IS_ACTIVE', db.Boolean, default=True)  # Активна ли запись в очереди
    
    def calculate_score(self):
        """Рассчитывает балл на основе критериев"""
        score = 0
        # Дети дают баллы
        if self.has_children:
            score += 10
        # Работа дает баллы
        if self.has_work:
            score += 15
        # Нарушения закона уменьшают баллы
        if self.has_law_violations:
            score -= 20
        # Время в очереди (чем дольше, тем больше баллов)
        if self.added_at:
            days_in_queue = (datetime.utcnow() - self.added_at).days
            score += days_in_queue * 0.5  # 0.5 балла за каждый день
        return int(score)
    
    def to_dict(self):
        return {
            'id': self.id,
            'repatriant_id': self.repatriant_id,
            'has_children': self.has_children,
            'has_work': self.has_work,
            'has_law_violations': self.has_law_violations,
            'total_score': self.total_score,
            'queue_position': self.queue_position,
            'added_at': self.added_at.strftime('%Y-%m-%d %H:%M:%S') if self.added_at else None,
            'is_active': self.is_active
        }

# Функция для преобразования текстовых полей в верхний регистр
def uppercase_string_fields(target, exclude_fields=None):
    """Преобразует все строковые поля модели в верхний регистр"""
    if exclude_fields is None:
        # Исключаем только технические поля: пароли, бинарные данные, пути к файлам
        exclude_fields = {'password_hash', 'avatar_path', 'documents_path', 'file', 'photo', 'file_jil', 'f_name', 'f_name_jil'}
    
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
                    # Преобразуем в верхний регистр
                    setattr(target, attr_name, value.upper())
            except (AttributeError, TypeError, ValueError):
                # Если возникла ошибка при доступе к полю, пропускаем
                continue
    except Exception as e:
        # Если возникла ошибка при доступе к таблице, используем резервный подход
        # Проходим по всем атрибутам объекта через __dict__
        if hasattr(target, '__dict__'):
            for attr_name, value in target.__dict__.items():
                if attr_name.startswith('_') or attr_name.lower() in exclude_fields_lower:
                    continue
                if value is not None and isinstance(value, str) and value.strip():
                    try:
                        setattr(target, attr_name, value.upper())
                    except (AttributeError, TypeError, ValueError):
                        continue

# События SQLAlchemy для автоматического преобразования в верхний регистр
@event.listens_for(Repatriant, 'before_insert')
@event.listens_for(Repatriant, 'before_update')
def receive_before_insert_update_repatriant(mapper, connection, target):
    """Автоматически преобразует текстовые поля Repatriant в верхний регистр"""
    # Исключаем технические поля: пароли, бинарные данные, пути к файлам, email
    exclude_fields = {'password_hash', 'avatar_path', 'documents_path', 'file', 'photo', 'file_jil', 'f_name', 'f_name_jil', 'mail'}
    uppercase_string_fields(target, exclude_fields)

@event.listens_for(Child, 'before_insert')
@event.listens_for(Child, 'before_update')
def receive_before_insert_update_child(mapper, connection, target):
    """Автоматически преобразует текстовые поля Child в верхний регистр"""
    exclude_fields = {}
    uppercase_string_fields(target, exclude_fields)

@event.listens_for(FamilyMember, 'before_insert')
@event.listens_for(FamilyMember, 'before_update')
def receive_before_insert_update_family(mapper, connection, target):
    """Автоматически преобразует текстовые поля FamilyMember в верхний регистр"""
    exclude_fields = {}
    uppercase_string_fields(target, exclude_fields)

@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def receive_before_insert_update_user(mapper, connection, target):
    """Автоматически преобразует текстовые поля User в верхний регистр, кроме паролей"""
    # Для пользователей исключаем пароли и пути к файлам (если есть)
    exclude_fields = {'password_hash', 'username'}  # username оставляем как есть для логина
    uppercase_string_fields(target, exclude_fields)

# Функции для работы с файлами
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    """Проверяет разрешенные расширения файлов"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file, folder, prefix=''):
    """Сохраняет загруженный файл и возвращает путь к нему"""
    if file and allowed_file(file.filename):
        # Генерируем уникальное имя файла
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
        
        print(f"Сохраняем файл: {unique_filename} в папку: {folder}")
        
        # Выбираем лучший диск для сохранения
        if folder in ['documents', 'avatars']:
            # Для документов и аватарок используем равномерное распределение
            best_disk_path = get_best_disk()
            upload_path = best_disk_path
            relative_path = f"{folder}/{unique_filename}"
            print(f"Выбран диск: {best_disk_path}")
        else:
            # Остальные файлы в старую папку (для совместимости)
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
            relative_path = os.path.join(folder, unique_filename)
            print(f"Используем старую папку: {upload_path}")
        
        # Создаем папку если не существует
        os.makedirs(upload_path, exist_ok=True)
        print(f"Папка создана/проверена: {upload_path}")
        
        # Сохраняем файл
        file_path = os.path.join(upload_path, unique_filename)
        print(f"Сохраняем файл по пути: {file_path}")
        file.save(file_path)
        
        # Проверяем, что файл действительно сохранился
        if os.path.exists(file_path):
            print(f"✓ Файл успешно сохранен: {file_path}")
        else:
            print(f"✗ ОШИБКА: Файл не найден после сохранения: {file_path}")
        
        # Возвращаем относительный путь с прямыми слешами
        result_path = relative_path.replace('\\', '/')
        print(f"Возвращаем путь: {result_path}")
        return result_path
    return None

def delete_file(file_path):
    """Удаляет файл с диска"""
    if file_path:
        # Определяем полный путь в зависимости от типа файла
        if file_path.startswith('documents/') or file_path.startswith('avatars/'):
            # Файлы на дисках D или E
            folder_name = file_path.split('/')[0]  # documents или avatars
            filename = file_path.split('/')[1]     # имя файла
            
            # Ищем файл на всех дисках
            for disk in app.config['STORAGE_DISKS']:
                full_path = os.path.join(disk['path'], filename)
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                        print(f"Файл удален с {disk['name']}: {filename}")
                        return True
                    except OSError as e:
                        print(f"Ошибка удаления файла с {disk['name']}: {e}")
                        continue
        else:
            # Остальные файлы в старой папке
            normalized_path = file_path.replace('/', '\\')
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], normalized_path)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                    return True
                except OSError:
                    return False
    return False

# Функции авторизации
def login_required(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # Проверяем, не истекла ли сессия (24 часа)
        if 'last_activity' in session:
            last_activity = datetime.fromisoformat(session['last_activity'])
            if datetime.now() - last_activity > timedelta(hours=24):
                session.clear()
                flash('Сессия истекла. Пожалуйста, войдите снова.', 'warning')
                return redirect(url_for('login'))
        
        # Обновляем время последней активности
        session['last_activity'] = datetime.now().isoformat()
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Декоратор для проверки прав администратора"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user = User.query.get(session['user_id'])
        if not user or user.role != 'ADMIN':
            flash('Недостаточно прав для доступа к этой странице.', 'error')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function

def check_repatriant_status(rep_status_date):
    """Проверяет статус репатрианта и возвращает информацию о его состоянии"""
    if not rep_status_date:
        return {
            'status': 'not_set',
            'color': 'gray',
            'text': 'Не указан',
            'is_expired': False,
            'days_left': None
        }
    
    # Вычисляем дату истечения (5 лет с даты получения статуса)
    expiration_date = rep_status_date + timedelta(days=5*365)  # 5 лет
    today = datetime.now().date()
    
    if today > expiration_date:
        # Статус истек
        days_expired = (today - expiration_date).days
        return {
            'status': 'expired',
            'color': 'red',
            'text': f'Истек ({days_expired} дн. назад)',
            'is_expired': True,
            'days_left': -days_expired
        }
    else:
        # Статус действует
        days_left = (expiration_date - today).days
        return {
            'status': 'active',
            'color': 'green',
            'text': f'Действует ({days_left} дн.)',
            'is_expired': False,
            'days_left': days_left
        }

def log_user_action(action, repatriant_id=None):
    """Логирует действие пользователя"""
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        username = user.username if user else 'Unknown'
        
        # Преобразуем действие в верхний регистр
        action_upper = action.upper() if action else ''
        
        # Получаем следующий ID_LOG
        max_log_id = db.session.execute(text('SELECT MAX("ID_LOG") FROM "LOG"')).scalar()
        next_log_id = (max_log_id or 0) + 1
        
        # Записываем в таблицу LOG
        db.session.execute(text("""
            INSERT INTO "LOG" ("ID_LOG", "LIST_ID", "USER_NAME", "DATE_IZM", "TIME_IZM")
            VALUES (:id_log, :list_id, :username, :date_izm, :time_izm)
        """), {
            'id_log': next_log_id,
            'list_id': repatriant_id,  # ID репатрианта или None для общих действий
            'username': f"{username}: {action_upper}",
            'date_izm': datetime.now().date(),
            'time_izm': datetime.now().time()
        })
        
        db.session.commit()

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

# Добавляем функцию в контекст шаблонов
@app.context_processor
def utility_processor():
    return dict(check_repatriant_status=check_repatriant_status)

if __name__ == '__main__':
    import sys
    import socket
    
    def get_local_ip():
        """Получает локальный IP-адрес"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == '--local':
        # Запуск для локальной сети с подробной информацией
        local_ip = get_local_ip()
        port = 5000
        
        print("=" * 60)
        print("🚀 ЗАПУСК СИСТЕМЫ РЕПАТРИАНТОВ В ЛОКАЛЬНОЙ СЕТИ")
        print("=" * 60)
        print(f"🌐 Локальный IP: {local_ip}")
        print(f"🔌 Порт: {port}")
        print()
        print("🌍 ДОСТУП К ПРИЛОЖЕНИЮ:")
        print(f"💻 Локально:     http://localhost:{port}")
        print(f"🏠 Локальная сеть: http://{local_ip}:{port}")
        print()
        print("📱 ДЛЯ ДРУГИХ УСТРОЙСТВ В СЕТИ:")
        print(f"1. Убедитесь, что устройство подключено к той же сети")
        print(f"2. Откройте браузер и перейдите по адресу:")
        print(f"   http://{local_ip}:{port}")
        print("=" * 60)
        
        with app.app_context():
            db.create_all()
        app.run(debug=True, host='0.0.0.0', port=port, threaded=True)
    else:
        # Обычный запуск с отображением локального IP
        local_ip = get_local_ip()
        port = 5000
        
        print("=" * 60)
        print("🚀 СИСТЕМА РЕПАТРИАНТОВ")
        print("=" * 60)
        print(f"🌐 Локальный IP: {local_ip}")
        print(f"🔌 Порт: {port}")
        print()
        print("🌍 ДОСТУП К ПРИЛОЖЕНИЮ:")
        print(f"💻 Локально:     http://localhost:{port}")
        print(f"🏠 Локальная сеть: http://{local_ip}:{port}")
        print("=" * 60)
        
        with app.app_context():
            db.create_all()
        app.run(debug=True, host='0.0.0.0', port=port, threaded=True)
