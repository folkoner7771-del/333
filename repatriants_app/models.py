from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import event

from .extensions import db
from .utils.text import uppercase_string_fields

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

