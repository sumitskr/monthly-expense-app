from functools import wraps
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import Config
from models import db, User, Salary, EMI, Saving, Expense, SystemSetting
from utils import generate_otp, send_otp_email, calculate_monthly_cashflow, generate_cashflow_forecast, format_currency, set_setting, get_setting

app = Flask(__name__)
app.config.from_object(Config)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=2)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Context Processor for Templates
@app.context_processor
def inject_globals():
    now_ym = datetime.now().strftime('%Y-%m')
    return {
        'current_month_ym': now_ym,
        'format_currency': format_currency,
        'now_year': datetime.now().year
    }

# Admin Required Decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Verification Required Decorator
def verification_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and not current_user.is_verified:
            flash("Please verify your email via OTP to continue.", "warning")
            return redirect(url_for('verify_otp'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- AUTH ROUTES ----------------- #

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not full_name or not email or not password:
            flash("Please fill out all required fields.", "warning")
            return render_template('auth/register.html')

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template('auth/register.html')

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template('auth/register.html')

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("An account with this email already exists. Please login.", "danger")
            return redirect(url_for('login'))

        otp = generate_otp()
        user = User(
            full_name=full_name,
            email=email,
            is_verified=False,
            is_admin=False,
            otp_code=otp,
            otp_created_at=datetime.now(timezone.utc)
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()

        # Send OTP
        success, msg = send_otp_email(user.email, otp)
        flash(msg, "info" if success else "warning")

        # Auto login as unverified user to facilitate OTP verification
        session.permanent = True
        login_user(user, remember=True)
        session['unverified_email'] = email
        return redirect(url_for('verify_otp'))

    return render_template('auth/register.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
@login_required
def verify_otp():
    if current_user.is_verified:
        flash("Your account is already verified!", "success")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        
        if current_user.otp_code and entered_otp == current_user.otp_code:
            current_user.is_verified = True
            current_user.otp_code = None
            db.session.commit()
            flash("Email successfully verified! Welcome aboard.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid OTP code. Please check and try again.", "danger")

    return render_template('auth/verify_otp.html', user=current_user)

@app.route('/resend-otp', methods=['POST'])
@login_required
def resend_otp():
    if current_user.is_verified:
        return redirect(url_for('dashboard'))
        
    new_otp = generate_otp()
    current_user.otp_code = new_otp
    current_user.otp_created_at = datetime.now(timezone.utc)
    db.session.commit()

    success, msg = send_otp_email(current_user.email, new_otp)
    flash(msg, "info" if success else "warning")
    return redirect(url_for('verify_otp'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template('auth/login.html')

        session.permanent = True
        login_user(user, remember=True)
        flash(f"Welcome back, {user.full_name}!", "success")

        if not user.is_verified:
            flash("Please verify your email address to unlock full features.", "warning")
            return redirect(url_for('verify_otp'))

        if user.is_admin:
            return redirect(url_for('admin_dashboard'))

        return redirect(url_for('dashboard'))

    return render_template('auth/login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# ----------------- MAIN DASHBOARD & FINANCIAL CORE ----------------- #

@app.route('/')
@app.route('/dashboard')
@login_required
@verification_required
def dashboard():
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    cashflow = calculate_monthly_cashflow(current_user.id, selected_month)

    # Format historical month list for dropdown navigation
    now = datetime.now()
    cur_year = now.year
    cur_month = now.month
    
    months_options = []
    # 12 months in past to 6 months in future
    for offset in range(-12, 7):
        m = cur_month + offset
        y = cur_year
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        ym_str = f"{y:04d}-{m:02d}"
        dt = datetime(y, m, 1)
        label = dt.strftime('%B %Y')
        months_options.append({'val': ym_str, 'label': label})
    
    months_options.sort(key=lambda x: x['val'], reverse=True)

    return render_template(
        'dashboard.html',
        cashflow=cashflow,
        selected_month=selected_month,
        months_options=months_options
    )

# ----------------- CASHFLOW FORECAST ROUTE ----------------- #

@app.route('/forecast')
@login_required
@verification_required
def forecast():
    start_ym = request.args.get('start_month', datetime.now().strftime('%Y-%m'))
    end_ym = request.args.get('end_month', '')
    months_horizon = request.args.get('months', '')

    if not end_ym and not months_horizon:
        # Default to 12 months from start_ym
        end_parts = [int(p) for p in start_ym.split('-')]
        ey = end_parts[0] + 1
        em = end_parts[1]
        end_ym = f"{ey:04d}-{em:02d}"

    forecast_data = generate_cashflow_forecast(
        user_id=current_user.id,
        start_ym=start_ym,
        end_ym=end_ym if end_ym else None,
        horizon_months=int(months_horizon) if (months_horizon and months_horizon.isdigit()) else None
    )

    return render_template(
        'forecast.html',
        forecast=forecast_data,
        start_ym=start_ym,
        end_ym=forecast_data['end_ym']
    )

# ----------------- SALARY MANAGEMENT ----------------- #

@app.route('/salary', methods=['GET', 'POST'])
@login_required
@verification_required
def salary():
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))

    if request.method == 'POST':
        month_year = request.form.get('month_year', selected_month).strip()
        try:
            amount = float(request.form.get('amount', 0.0))
        except ValueError:
            amount = 0.0
        notes = request.form.get('notes', '').strip()

        if amount < 0:
            flash("Salary amount cannot be negative.", "danger")
            return redirect(url_for('salary', month=month_year))

        salary_rec = Salary.query.filter_by(user_id=current_user.id, month_year=month_year).first()
        if salary_rec:
            salary_rec.amount = amount
            salary_rec.notes = notes
            flash(f"Updated salary for {month_year} to {format_currency(amount)}", "success")
        else:
            salary_rec = Salary(
                user_id=current_user.id,
                month_year=month_year,
                amount=amount,
                notes=notes
            )
            db.session.add(salary_rec)
            flash(f"Saved salary for {month_year}: {format_currency(amount)}", "success")

        db.session.commit()
        return redirect(url_for('dashboard', month=month_year))

    salaries = Salary.query.filter_by(user_id=current_user.id).order_by(Salary.month_year.desc()).all()
    current_salary_rec = Salary.query.filter_by(user_id=current_user.id, month_year=selected_month).first()

    return render_template(
        'salary.html',
        salaries=salaries,
        selected_month=selected_month,
        current_salary_rec=current_salary_rec
    )

@app.route('/salary/delete/<int:id>', methods=['POST'])
@login_required
@verification_required
def delete_salary(id):
    salary_rec = Salary.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    ym = salary_rec.month_year
    db.session.delete(salary_rec)
    db.session.commit()
    flash(f"Deleted salary entry for {ym}.", "info")
    return redirect(url_for('salary'))

# ----------------- FIXED EMIS MANAGEMENT ----------------- #

@app.route('/emis', methods=['GET', 'POST'])
@login_required
@verification_required
def emis():
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', 'General').strip()
        entry_mode = request.form.get('entry_mode', 'by_start_date').strip()
        
        try:
            monthly_amount = float(request.form.get('monthly_amount', 0.0))
        except ValueError:
            monthly_amount = 0.0

        if entry_mode == 'by_paid_pending':
            try:
                months_paid = max(1, int(request.form.get('months_paid', 1)))
                months_pending = max(0, int(request.form.get('months_pending', 0)))
            except ValueError:
                flash("Invalid numeric value for months paid or pending.", "danger")
                return redirect(url_for('emis'))

            tenure_months = months_paid + months_pending
            
            # Calculate start_month: selected_month minus (months_paid - 1)
            parts = [int(p) for p in selected_month.split('-')]
            y, m = parts[0], parts[1]
            m -= (months_paid - 1)
            while m < 1:
                m += 12
                y -= 1
            start_month = f"{y:04d}-{m:02d}"
        else:
            try:
                tenure_months = int(request.form.get('tenure_months', 12))
            except ValueError:
                tenure_months = 12
            start_month = request.form.get('start_month', selected_month).strip()

        notes = request.form.get('notes', '').strip()

        if not name or monthly_amount <= 0 or tenure_months <= 0:
            flash("Please provide a valid EMI name, positive amount, and tenure.", "warning")
            return redirect(url_for('emis'))

        emi = EMI(
            user_id=current_user.id,
            name=name,
            category=category,
            monthly_amount=monthly_amount,
            start_month=start_month,
            tenure_months=tenure_months,
            notes=notes,
            is_active=True
        )
        db.session.add(emi)
        db.session.commit()
        flash(f"Added EMI tenure: '{name}' ({format_currency(monthly_amount)}/mo for {tenure_months} months total)", "success")
        return redirect(url_for('emis'))

    user_emis = EMI.query.filter_by(user_id=current_user.id).order_by(EMI.created_at.desc()).all()
    
    # Calculate detailed status for each EMI for selected month
    emi_details = []
    total_active_monthly_emi = 0.0
    for e in user_emis:
        is_active_now = e.is_active_for_month(selected_month)
        rem = e.remaining_months(selected_month)
        comp = e.months_completed(selected_month)
        pct = round((comp / e.tenure_months * 100), 1) if e.tenure_months > 0 else 100
        if is_active_now:
            total_active_monthly_emi += e.monthly_amount
        emi_details.append({
            'emi': e,
            'is_active_now': is_active_now,
            'remaining': rem,
            'completed': comp,
            'progress_pct': pct
        })

    return render_template(
        'emis.html',
        emi_details=emi_details,
        total_active_monthly_emi=total_active_monthly_emi,
        selected_month=selected_month
    )

@app.route('/emis/toggle/<int:id>', methods=['POST'])
@login_required
@verification_required
def toggle_emi(id):
    emi = EMI.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    emi.is_active = not emi.is_active
    db.session.commit()
    status_str = "activated" if emi.is_active else "paused"
    flash(f"EMI '{emi.name}' has been {status_str}.", "info")
    return redirect(url_for('emis'))

@app.route('/emis/delete/<int:id>', methods=['POST'])
@login_required
@verification_required
def delete_emi(id):
    emi = EMI.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    name = emi.name
    db.session.delete(emi)
    db.session.commit()
    flash(f"Deleted EMI '{name}'.", "info")
    return redirect(url_for('emis'))

# ----------------- SAVINGS CATEGORIES ----------------- #

@app.route('/savings', methods=['GET', 'POST'])
@login_required
@verification_required
def savings():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', 'FD').strip()
        try:
            monthly_amount = float(request.form.get('monthly_amount', 0.0))
        except ValueError:
            monthly_amount = 0.0
        notes = request.form.get('notes', '').strip()

        if not name or monthly_amount <= 0:
            flash("Please enter a valid savings title and positive monthly reduction amount.", "warning")
            return redirect(url_for('savings'))

        saving = Saving(
            user_id=current_user.id,
            name=name,
            category=category,
            monthly_amount=monthly_amount,
            notes=notes,
            is_active=True
        )
        db.session.add(saving)
        db.session.commit()
        flash(f"Added savings category: '{name}' ({category}) - {format_currency(monthly_amount)}/mo", "success")
        return redirect(url_for('savings'))

    user_savings = Saving.query.filter_by(user_id=current_user.id).order_by(Saving.created_at.desc()).all()
    total_savings_monthly = sum(s.monthly_amount for s in user_savings if s.is_active)

    return render_template(
        'savings.html',
        savings=user_savings,
        total_savings_monthly=total_savings_monthly
    )

@app.route('/savings/toggle/<int:id>', methods=['POST'])
@login_required
@verification_required
def toggle_saving(id):
    saving = Saving.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    saving.is_active = not saving.is_active
    db.session.commit()
    status_str = "activated" if saving.is_active else "paused"
    flash(f"Savings category '{saving.name}' is now {status_str}.", "info")
    return redirect(url_for('savings'))

@app.route('/savings/delete/<int:id>', methods=['POST'])
@login_required
@verification_required
def delete_saving(id):
    saving = Saving.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    name = saving.name
    db.session.delete(saving)
    db.session.commit()
    flash(f"Deleted savings category '{name}'.", "info")
    return redirect(url_for('savings'))

# ----------------- EXPENSES TRACKING ----------------- #

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
@verification_required
def expenses():
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', 'Miscellaneous').strip()
        month_year = request.form.get('month_year', selected_month).strip()
        expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
        try:
            amount = float(request.form.get('amount', 0.0))
        except ValueError:
            amount = 0.0

        if not title or amount <= 0:
            flash("Please provide a valid title and positive expense amount.", "warning")
            return redirect(url_for('expenses', month=month_year))

        exp = Expense(
            user_id=current_user.id,
            month_year=month_year,
            title=title,
            category=category,
            amount=amount,
            expense_date=expense_date
        )
        db.session.add(exp)
        db.session.commit()
        flash(f"Added expense '{title}' ({format_currency(amount)}) for {month_year}.", "success")
        return redirect(url_for('expenses', month=month_year))

    month_expenses = Expense.query.filter_by(
        user_id=current_user.id,
        month_year=selected_month
    ).order_by(Expense.expense_date.desc()).all()

    total_expense = sum(e.amount for e in month_expenses)

    return render_template(
        'expenses.html',
        expenses=month_expenses,
        selected_month=selected_month,
        total_expense=total_expense
    )

@app.route('/expenses/delete/<int:id>', methods=['POST'])
@login_required
@verification_required
def delete_expense(id):
    exp = Expense.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    ym = exp.month_year
    db.session.delete(exp)
    db.session.commit()
    flash("Deleted expense entry.", "info")
    return redirect(url_for('expenses', month=ym))

# ----------------- ADMIN PANEL ----------------- #

@app.route('/admin')
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    verified_users = User.query.filter_by(is_verified=True).count()
    total_emis = EMI.query.count()
    total_savings = Saving.query.count()
    total_expenses = Expense.query.count()

    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        verified_users=verified_users,
        total_emis=total_emis,
        total_savings=total_savings,
        total_expenses=total_expenses,
        recent_users=recent_users,
        smtp_server=get_setting('SMTP_SERVER', ''),
        smtp_user=get_setting('SMTP_USER', '')
    )

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/toggle-verify/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_verify(id):
    user = User.query.get_or_404(id)
    user.is_verified = not user.is_verified
    db.session.commit()
    flash(f"Verification status updated for {user.email}.", "success")
    return redirect(url_for('admin_users'))

@app.route('/admin/users/toggle-admin/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash("You cannot revoke your own admin rights.", "danger")
        return redirect(url_for('admin_users'))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"Admin privilege updated for {user.email}.", "success")
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for('admin_users'))
    email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f"User {email} deleted from system.", "info")
    return redirect(url_for('admin_users'))

@app.route('/admin/smtp', methods=['POST'])
@login_required
@admin_required
def admin_save_smtp():
    set_setting('SMTP_SERVER', request.form.get('smtp_server', '').strip())
    set_setting('SMTP_PORT', request.form.get('smtp_port', '587').strip())
    set_setting('SMTP_USER', request.form.get('smtp_user', '').strip())
    set_setting('SMTP_PASS', request.form.get('smtp_pass', '').strip())
    set_setting('SENDER_EMAIL', request.form.get('sender_email', '').strip())
    flash("SMTP configurations saved successfully.", "success")
    return redirect(url_for('admin_dashboard'))

# ----------------- DB INITIALIZER & SEEDER ----------------- #

def init_db():
    with app.app_context():
        db.create_all()

        # Seed Admin User if not existing
        admin = User.query.filter_by(email='admin@expense.com').first()
        if not admin:
            admin = User(
                full_name='System Admin',
                email='admin@expense.com',
                is_verified=True,
                is_admin=True
            )
            admin.set_password('Admin@123456')
            db.session.add(admin)

        # Seed Demo User if not existing
        demo_user = User.query.filter_by(email='demo@expense.com').first()
        if not demo_user:
            demo_user = User(
                full_name='Rahul Sharma',
                email='demo@expense.com',
                is_verified=True,
                is_admin=False
            )
            demo_user.set_password('User@123456')
            db.session.add(demo_user)
            db.session.commit()

            # Seed Demo Data for Demo User
            curr_ym = datetime.now().strftime('%Y-%m')

            # Salary
            salary1 = Salary(user_id=demo_user.id, month_year=curr_ym, amount=125000.0, notes='Monthly Net Salary')
            db.session.add(salary1)

            # EMIs
            emi1 = EMI(user_id=demo_user.id, name='Housing Loan', category='Real Estate', monthly_amount=28000.0, start_month='2025-01', tenure_months=120, notes='HDFC Home Loan')
            emi2 = EMI(user_id=demo_user.id, name='Car Loan (Creta)', category='Vehicle', monthly_amount=14500.0, start_month='2025-06', tenure_months=60, notes='Axis Auto Loan')
            emi3 = EMI(user_id=demo_user.id, name='iPhone 15 Pro EMI', category='Gadgets', monthly_amount=4800.0, start_month=curr_ym, tenure_months=12, notes='No Cost EMI 0% interest')
            db.session.add_all([emi1, emi2, emi3])

            # Savings Categories (FD, RD, Flow Money)
            sav1 = Saving(user_id=demo_user.id, name='Fixed Deposit (HDFC)', category='FD', monthly_amount=15000.0, notes='Auto-renew FD 7.2% p.a.')
            sav2 = Saving(user_id=demo_user.id, name='Recurring Deposit (SBI)', category='RD', monthly_amount=10000.0, notes='Monthly RD')
            sav3 = Saving(user_id=demo_user.id, name='Nifty 50 Index Mutual Fund', category='Flow Money', monthly_amount=12000.0, notes='SIP Flow Money')
            sav4 = Saving(user_id=demo_user.id, name='Emergency Liquidity Pot', category='Emergency Savings', monthly_amount=5000.0, notes='Liquid bank pot')
            db.session.add_all([sav1, sav2, sav3, sav4])

            # Expenses
            exp1 = Expense(user_id=demo_user.id, month_year=curr_ym, title='Apartment Maintenance & Utilities', category='Rent & Utilities', amount=4200.0, expense_date=datetime.now().strftime('%Y-%m-05'))
            exp2 = Expense(user_id=demo_user.id, month_year=curr_ym, title='Supermarket & Groceries', category='Groceries', amount=7500.0, expense_date=datetime.now().strftime('%Y-%m-10'))
            exp3 = Expense(user_id=demo_user.id, month_year=curr_ym, title='Family Dining & Weekend Outing', category='Dining & Leisure', amount=3800.0, expense_date=datetime.now().strftime('%Y-%m-15'))
            exp4 = Expense(user_id=demo_user.id, month_year=curr_ym, title='Fuel & Broadband', category='Utilities', amount=3500.0, expense_date=datetime.now().strftime('%Y-%m-18'))
            db.session.add_all([exp1, exp2, exp3, exp4])

        db.session.commit()

init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
