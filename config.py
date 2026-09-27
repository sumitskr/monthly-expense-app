import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key_monthly_expense_app_2026_x89q2')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///monthly_expense.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
