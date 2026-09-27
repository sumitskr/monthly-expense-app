from datetime import datetime, timezone, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    otp_code = db.Column(db.String(6), nullable=True)
    otp_created_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    salaries = db.relationship('Salary', backref='user', lazy=True, cascade='all, delete-orphan')
    emis = db.relationship('EMI', backref='user', lazy=True, cascade='all, delete-orphan')
    savings = db.relationship('Saving', backref='user', lazy=True, cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Salary(db.Model):
    __tablename__ = 'salaries'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    month_year = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    amount = db.Column(db.Float, nullable=False, default=0.0)
    notes = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'month_year', name='_user_month_uc'),)

class EMI(db.Model):
    __tablename__ = 'emis'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='General')  # e.g., Gadget, Vehicle, Home
    monthly_amount = db.Column(db.Float, nullable=False, default=0.0)
    start_month = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    tenure_months = db.Column(db.Integer, nullable=False, default=12)  # e.g. 12, 24, 36
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def get_month_index(self, ym_str):
        parts = ym_str.split('-')
        return int(parts[0]) * 12 + int(parts[1])

    def is_active_for_month(self, target_ym):
        if not self.is_active:
            return False
        try:
            start_idx = self.get_month_index(self.start_month)
            target_idx = self.get_month_index(target_ym)
            end_idx = start_idx + self.tenure_months - 1
            return start_idx <= target_idx <= end_idx
        except Exception:
            return False

    def remaining_months(self, target_ym):
        try:
            start_idx = self.get_month_index(self.start_month)
            target_idx = self.get_month_index(target_ym)
            end_idx = start_idx + self.tenure_months - 1
            if target_idx > end_idx:
                return 0
            if target_idx < start_idx:
                return self.tenure_months
            return end_idx - target_idx + 1
        except Exception:
            return 0

    def months_completed(self, target_ym):
        try:
            start_idx = self.get_month_index(self.start_month)
            target_idx = self.get_month_index(target_ym)
            if target_idx < start_idx:
                return 0
            completed = target_idx - start_idx + 1
            return min(completed, self.tenure_months)
        except Exception:
            return 0

class Saving(db.Model):
    __tablename__ = 'savings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # FD, RD, Flow Money, Mutual Fund, Emergency Fund
    monthly_amount = db.Column(db.Float, nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    month_year = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    title = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='Miscellaneous')
    amount = db.Column(db.Float, nullable=False, default=0.0)
    expense_date = db.Column(db.String(10), nullable=True)  # YYYY-MM-DD
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)
