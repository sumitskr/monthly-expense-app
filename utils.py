import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from models import db, User, Salary, EMI, Saving, Expense, SystemSetting

def generate_otp():
    """Generates a random 6-digit numeric OTP."""
    return f"{random.randint(100000, 999999)}"

def send_otp_email(user_email, otp_code):
    """
    Attempts to send OTP via SMTP if settings are configured in DB.
    Returns (success: bool, message: str)
    """
    smtp_server = get_setting('SMTP_SERVER', '')
    smtp_port = get_setting('SMTP_PORT', '587')
    smtp_user = get_setting('SMTP_USER', '')
    smtp_pass = get_setting('SMTP_PASS', '').replace(' ', '')  # remove spaces if pasted from Google App Passwords
    sender_email = get_setting('SENDER_EMAIL', smtp_user or 'noreply@expenseapp.com')

    if not smtp_server or not smtp_user or not smtp_pass:
        # SMTP not configured message
        return False, "SMTP email server is not configured in Admin Panel. Please ask Admin to setup Gmail SMTP."

    try:
        msg = MIMEMultipart()
        msg['From'] = f"CashFlowPro <{sender_email}>"
        msg['To'] = user_email
        msg['Subject'] = "Your Verification OTP - Monthly Cash Flow Manager"
        
        body = f"""Hello,

Your One-Time Password (OTP) for account verification is:

  🔒 {otp_code}

This code is valid for 10 minutes. Please enter this code on the verification page to activate your account.

If you did not request this, please ignore this email.

Best regards,
Monthly Expense App Team
"""
        msg.attach(MIMEText(body, 'plain'))

        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_server, port)
        else:
            server = smtplib.SMTP(smtp_server, port)
            server.starttls()
            
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return True, f"Verification OTP code sent to {user_email}. Please check your email inbox."
    except Exception as e:
        return False, f"Failed to send email via SMTP: {str(e)}"


def get_setting(key, default=''):
    setting = SystemSetting.query.get(key)
    return setting.value if setting and setting.value is not None else default

def set_setting(key, value):
    setting = SystemSetting.query.get(key)
    if not setting:
        setting = SystemSetting(key=key, value=str(value))
        db.session.add(setting)
    else:
        setting.value = str(value)
    db.session.commit()

def calculate_monthly_cashflow(user_id, month_year):
    """
    Computes monthly salary, active EMIs, recurring savings, expenses, and available cash.
    """
    # 1. Salary
    salary_record = Salary.query.filter_by(user_id=user_id, month_year=month_year).first()
    salary_amount = salary_record.amount if salary_record else 0.0
    is_salary_set = salary_record is not None

    # If salary for this month is not explicitly added, check if there is a previous salary record
    carried_forward = False
    if not is_salary_set:
        latest_prev = Salary.query.filter(
            Salary.user_id == user_id,
            Salary.month_year <= month_year
        ).order_by(Salary.month_year.desc()).first()
        if latest_prev:
            salary_amount = latest_prev.amount
            carried_forward = True

    # 2. EMIs active for this month
    all_emis = EMI.query.filter_by(user_id=user_id).all()
    active_emis = [e for e in all_emis if e.is_active_for_month(month_year)]
    total_emi_amount = sum(e.monthly_amount for e in active_emis)

    # 3. Savings categories active
    active_savings = Saving.query.filter_by(user_id=user_id, is_active=True).all()
    total_savings_amount = sum(s.monthly_amount for s in active_savings)

    # Breakdown by savings category
    savings_by_cat = {}
    for s in active_savings:
        savings_by_cat[s.category] = savings_by_cat.get(s.category, 0.0) + s.monthly_amount

    # 4. Expenses for this month
    expenses = Expense.query.filter_by(user_id=user_id, month_year=month_year).all()
    total_expense_amount = sum(e.amount for e in expenses)

    # If no specific expenses logged for this month, default to average or current month expenses
    if total_expense_amount == 0 and not is_salary_set:
        curr_ym = datetime.now().strftime('%Y-%m')
        curr_expenses = Expense.query.filter_by(user_id=user_id, month_year=curr_ym).all()
        total_expense_amount = sum(e.amount for e in curr_expenses)

    # Expense category breakdown
    expenses_by_cat = {}
    for e in expenses:
        expenses_by_cat[e.category] = expenses_by_cat.get(e.category, 0.0) + e.amount

    # 5. Financial Summary Math
    total_deductions = total_emi_amount + total_savings_amount + total_expense_amount
    available_cash = salary_amount - total_deductions

    # Percentages relative to gross salary
    emi_pct = (total_emi_amount / salary_amount * 100) if salary_amount > 0 else 0
    savings_pct = (total_savings_amount / salary_amount * 100) if salary_amount > 0 else 0
    expense_pct = (total_expense_amount / salary_amount * 100) if salary_amount > 0 else 0
    cash_pct = (available_cash / salary_amount * 100) if salary_amount > 0 else 0

    return {
        'month_year': month_year,
        'salary_amount': salary_amount,
        'is_salary_set': is_salary_set,
        'carried_forward': carried_forward,
        'active_emis': active_emis,
        'total_emi_amount': total_emi_amount,
        'active_savings': active_savings,
        'total_savings_amount': total_savings_amount,
        'savings_by_cat': savings_by_cat,
        'expenses': expenses,
        'total_expense_amount': total_expense_amount,
        'expenses_by_cat': expenses_by_cat,
        'total_deductions': total_deductions,
        'available_cash': available_cash,
        'emi_pct': round(emi_pct, 1),
        'savings_pct': round(savings_pct, 1),
        'expense_pct': round(expense_pct, 1),
        'cash_pct': round(cash_pct, 1),
    }

def generate_cashflow_forecast(user_id, start_ym=None, end_ym=None, horizon_months=None):
    """
    Generates a multi-month cashflow forecast supporting any custom start and end month calendar selection.
    Supports long-term horizons (e.g., 5, 10, 20, 30 years).
    """
    now = datetime.now()
    if not start_ym:
        start_ym = now.strftime('%Y-%m')

    start_parts = [int(p) for p in start_ym.split('-')]
    start_year, start_month = start_parts[0], start_parts[1]

    if end_ym:
        end_parts = [int(p) for p in end_ym.split('-')]
        end_year, end_month = end_parts[0], end_parts[1]
        calculated_months = (end_year - start_year) * 12 + (end_month - start_month) + 1
        horizon_months = max(1, min(calculated_months, 360))  # Max 30 years (360 months)
    elif horizon_months:
        horizon_months = max(1, min(int(horizon_months), 360))
    else:
        horizon_months = 12

    monthly_forecasts = []
    cumulative_cash = 0.0
    cumulative_savings = 0.0
    emis_ending_soon = []

    # Get baseline salary and baseline expenses
    base_cashflow = calculate_monthly_cashflow(user_id, start_ym)

    all_user_emis = EMI.query.filter_by(user_id=user_id, is_active=True).all()

    for i in range(horizon_months):
        m = start_month + i
        y = start_year
        while m > 12:
            m -= 12
            y += 1
        ym_str = f"{y:04d}-{m:02d}"
        month_label = datetime(y, m, 1).strftime('%b %Y')

        # Check explicit salary for month or fallback to baseline
        sal_rec = Salary.query.filter_by(user_id=user_id, month_year=ym_str).first()
        salary_val = sal_rec.amount if sal_rec else base_cashflow['salary_amount']

        # Check active EMIs for this future month
        active_emis_future = [e for e in all_user_emis if e.is_active_for_month(ym_str)]
        emi_val = sum(e.monthly_amount for e in active_emis_future)

        # Track which EMIs finish in this month
        for e in all_user_emis:
            if e.remaining_months(ym_str) == 1 and e not in emis_ending_soon:
                emis_ending_soon.append({
                    'emi_name': e.name,
                    'ending_month': ym_str,
                    'monthly_saved': e.monthly_amount
                })

        # Active savings
        savings_val = base_cashflow['total_savings_amount']

        # Expenses (explicit for month or baseline)
        exp_recs = Expense.query.filter_by(user_id=user_id, month_year=ym_str).all()
        if exp_recs:
            exp_val = sum(x.amount for x in exp_recs)
        else:
            exp_val = base_cashflow['total_expense_amount']

        # Financial Math for Month
        net_cash = salary_val - (emi_val + savings_val + exp_val)
        cumulative_cash += net_cash
        cumulative_savings += savings_val

        monthly_forecasts.append({
            'month_year': ym_str,
            'month_label': month_label,
            'salary': salary_val,
            'emi': emi_val,
            'active_emi_count': len(active_emis_future),
            'savings': savings_val,
            'expenses': exp_val,
            'net_cash': net_cash,
            'cumulative_cash': cumulative_cash,
            'cumulative_savings': cumulative_savings
        })

    total_projected_cash = cumulative_cash
    total_projected_savings = cumulative_savings

    last_month_ym = monthly_forecasts[-1]['month_year'] if monthly_forecasts else start_ym

    return {
        'start_ym': start_ym,
        'end_ym': last_month_ym,
        'horizon_months': horizon_months,
        'monthly_forecasts': monthly_forecasts,
        'total_projected_cash': total_projected_cash,
        'total_projected_savings': total_projected_savings,
        'emis_ending_soon': emis_ending_soon,
        'labels': [m['month_label'] for m in monthly_forecasts],
        'cash_data': [round(m['net_cash'], 2) for m in monthly_forecasts],
        'emi_data': [round(m['emi'], 2) for m in monthly_forecasts],
        'cum_cash_data': [round(m['cumulative_cash'], 2) for m in monthly_forecasts]
    }

def format_currency(val):
    if val is None:
        return "₹0"
    try:
        val_float = float(val)
        if val_float.is_integer():
            return f"₹{int(val_float):,}"
        return f"₹{val_float:,.2f}"
    except (ValueError, TypeError):
        return "₹0"
