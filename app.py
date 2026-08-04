import csv
import io
import os
import sqlite3
import uuid
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template,
    request, send_file, send_from_directory, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'expenses.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DEFAULT_CATEGORIES = [
    'Food', 'Transport', 'Housing', 'Utilities',
    'Entertainment', 'Health', 'Shopping', 'Other'
]
PAYMENT_METHODS = [
    'PhonePe / UPI', 'Cash', 'Debit Card', 'Credit Card', 'Bank Transfer'
]
INCOME_SOURCES = ['Salary', 'Freelance', 'Business', 'Investment', 'Gift', 'Refund', 'Other']
RECURRING_FREQUENCIES = ['Weekly', 'Monthly', 'Yearly']
ALLOWED_RECEIPT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _columns(db, table):
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})').fetchall()}


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA foreign_keys = ON')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS expense (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Cash',
            receipt_filename TEXT,
            notes TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            source TEXT NOT NULL,
            notes TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Overall',
            amount REAL NOT NULL,
            user_id INTEGER NOT NULL,
            UNIQUE(user_id, month, category),
            FOREIGN KEY (user_id) REFERENCES user (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS savings_goal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            current_amount REAL NOT NULL DEFAULT 0,
            target_date TEXT,
            created_at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS recurring_transaction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            category TEXT,
            payment_method TEXT,
            source TEXT,
            frequency TEXT NOT NULL,
            next_due_date TEXT NOT NULL,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user (id) ON DELETE CASCADE
        );
    ''')

    expense_columns = _columns(db, 'expense')
    if 'payment_method' not in expense_columns:
        db.execute("ALTER TABLE expense ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'Cash'")
    if 'receipt_filename' not in expense_columns:
        db.execute('ALTER TABLE expense ADD COLUMN receipt_filename TEXT')

    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if 'user_id' not in session:
        return None
    return get_db().execute(
        'SELECT * FROM user WHERE id = ?', (session['user_id'],)
    ).fetchone()


@app.context_processor
def inject_globals():
    return {
        'current_user': current_user(),
        'categories': DEFAULT_CATEGORIES,
        'payment_methods': PAYMENT_METHODS,
    }


@app.template_filter('to_date')
def to_date_filter(value):
    return datetime.strptime(value, '%Y-%m-%d').date()


@app.template_filter('inr')
def inr_filter(value):
    value = float(value or 0)
    whole, decimal = f'{value:.2f}'.split('.')
    sign = '-' if whole.startswith('-') else ''
    whole = whole.lstrip('-')
    if len(whole) > 3:
        last_three = whole[-3:]
        leading = whole[:-3]
        groups = []
        while leading:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        whole = ','.join(groups + [last_three])
    return f'{sign}₹{whole}.{decimal}'


def _parse_amount(raw, label='Amount'):
    try:
        value = float(raw)
        if value <= 0:
            return None, f'{label} must be greater than 0.'
        return value, None
    except (TypeError, ValueError):
        return None, f'Enter a valid {label.lower()}.'


def _valid_date(raw, fallback=None):
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date().isoformat()
    except (TypeError, ValueError):
        return fallback or date.today().isoformat()


def _allowed_receipt(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_RECEIPT_EXTENSIONS


def _save_receipt(file):
    if not file or not file.filename:
        return None, None
    if not _allowed_receipt(file.filename):
        return None, 'Receipt must be PNG, JPG, WEBP, or PDF.'
    original = secure_filename(file.filename)
    extension = original.rsplit('.', 1)[1].lower()
    filename = f'{uuid.uuid4().hex}.{extension}'
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return filename, None


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _next_due(value, frequency):
    if frequency == 'Weekly':
        return value + timedelta(days=7)
    if frequency == 'Yearly':
        return _add_months(value, 12)
    return _add_months(value, 1)


def process_recurring(user_id):
    db = get_db()
    items = db.execute(
        '''SELECT * FROM recurring_transaction
           WHERE user_id = ? AND active = 1 AND next_due_date <= ?''',
        (user_id, date.today().isoformat())
    ).fetchall()
    created = 0
    for item in items:
        due = datetime.strptime(item['next_due_date'], '%Y-%m-%d').date()
        safety = 0
        while due <= date.today() and safety < 120:
            if item['transaction_type'] == 'Income':
                db.execute(
                    '''INSERT INTO income
                       (title, amount, source, notes, date, created_at, user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (item['title'], item['amount'], item['source'] or 'Other',
                     item['notes'], due.isoformat(), datetime.now().isoformat(), user_id)
                )
            else:
                db.execute(
                    '''INSERT INTO expense
                       (title, amount, category, payment_method, notes, date, created_at, user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (item['title'], item['amount'], item['category'] or 'Other',
                     item['payment_method'] or 'Cash', item['notes'], due.isoformat(),
                     datetime.now().isoformat(), user_id)
                )
            created += 1
            safety += 1
            due = _next_due(due, item['frequency'])
        db.execute(
            'UPDATE recurring_transaction SET next_due_date = ? WHERE id = ?',
            (due.isoformat(), item['id'])
        )
    if items:
        db.commit()
    return created


def _month_context(raw_month):
    today = date.today()
    try:
        selected = datetime.strptime(raw_month, '%Y-%m').date().replace(day=1)
    except (TypeError, ValueError):
        selected = today.replace(day=1)
    previous = _add_months(selected, -1)
    following = _add_months(selected, 1)
    return selected, previous.strftime('%Y-%m'), following.strftime('%Y-%m')


def _expense_query(user_id, args):
    query = 'SELECT * FROM expense WHERE user_id = ?'
    params = [user_id]
    filters = {
        'search': args.get('search', '').strip(),
        'category': args.get('category', '').strip(),
        'payment_method': args.get('payment_method', '').strip(),
        'start_date': args.get('start_date', '').strip(),
        'end_date': args.get('end_date', '').strip(),
        'min_amount': args.get('min_amount', '').strip(),
        'max_amount': args.get('max_amount', '').strip(),
    }
    if filters['search']:
        query += ' AND (title LIKE ? OR notes LIKE ?)'
        term = f"%{filters['search']}%"
        params.extend([term, term])
    if filters['category'] in DEFAULT_CATEGORIES:
        query += ' AND category = ?'
        params.append(filters['category'])
    else:
        filters['category'] = ''
    if filters['payment_method'] in PAYMENT_METHODS:
        query += ' AND payment_method = ?'
        params.append(filters['payment_method'])
    else:
        filters['payment_method'] = ''
    if filters['start_date']:
        query += ' AND date >= ?'
        params.append(_valid_date(filters['start_date']))
    if filters['end_date']:
        query += ' AND date <= ?'
        params.append(_valid_date(filters['end_date']))
    try:
        if filters['min_amount']:
            query += ' AND amount >= ?'
            params.append(float(filters['min_amount']))
    except ValueError:
        filters['min_amount'] = ''
    try:
        if filters['max_amount']:
            query += ' AND amount <= ?'
            params.append(float(filters['max_amount']))
    except ValueError:
        filters['max_amount'] = ''
    query += ' ORDER BY date DESC, id DESC'
    return query, params, filters


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        db = get_db()
        error = None
        if not username or not email or not password:
            error = 'All fields are required.'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif db.execute('SELECT 1 FROM user WHERE username = ?', (username,)).fetchone():
            error = 'Username already taken.'
        elif db.execute('SELECT 1 FROM user WHERE email = ?', (email,)).fetchone():
            error = 'Email already registered.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                'INSERT INTO user (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
                (username, email, generate_password_hash(password), datetime.now().isoformat())
            )
            db.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_db().execute(
            'SELECT * FROM user WHERE username = ?', (username,)
        ).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/')
def index():
    return redirect(url_for('dashboard' if 'user_id' in session else 'login'))


@app.route('/dashboard')
@login_required
def dashboard():
    process_recurring(session['user_id'])
    db = get_db()
    selected, previous_month, next_month = _month_context(request.args.get('month'))
    month_key = selected.strftime('%Y-%m')
    month_start = selected.isoformat()
    month_end = selected.replace(day=monthrange(selected.year, selected.month)[1]).isoformat()

    expenses = db.execute(
        '''SELECT * FROM expense WHERE user_id = ? AND date BETWEEN ? AND ?
           ORDER BY date DESC, id DESC''',
        (session['user_id'], month_start, month_end)
    ).fetchall()
    incomes = db.execute(
        'SELECT * FROM income WHERE user_id = ? AND date BETWEEN ? AND ?',
        (session['user_id'], month_start, month_end)
    ).fetchall()
    budgets = db.execute(
        'SELECT * FROM budget WHERE user_id = ? AND month = ?',
        (session['user_id'], month_key)
    ).fetchall()

    total_spent = sum(row['amount'] for row in expenses)
    total_income = sum(row['amount'] for row in incomes)
    balance = total_income - total_spent
    overall = next((row['amount'] for row in budgets if row['category'] == 'Overall'), 0)
    budget_total = overall or sum(row['amount'] for row in budgets if row['category'] != 'Overall')
    budget_percent = min((total_spent / budget_total * 100), 100) if budget_total else 0

    category_totals = defaultdict(float)
    payment_totals = defaultdict(float)
    for row in expenses:
        category_totals[row['category']] += row['amount']
        payment_totals[row['payment_method'] or 'Cash'] += row['amount']

    monthly = db.execute(
        '''SELECT substr(date, 1, 7) month, SUM(amount) total
           FROM expense WHERE user_id = ? GROUP BY month ORDER BY month DESC LIMIT 6''',
        (session['user_id'],)
    ).fetchall()[::-1]
    goals = db.execute(
        'SELECT * FROM savings_goal WHERE user_id = ? ORDER BY id DESC LIMIT 3',
        (session['user_id'],)
    ).fetchall()

    return render_template(
        'dashboard.html', total_spent=total_spent, total_income=total_income,
        balance=balance, expense_count=len(expenses), recent_expenses=expenses[:5],
        selected_month=month_key, selected_month_name=selected.strftime('%B %Y'),
        previous_month=previous_month, next_month=next_month,
        category_labels=list(category_totals), category_values=list(category_totals.values()),
        payment_labels=list(payment_totals), payment_values=list(payment_totals.values()),
        month_labels=[row['month'] for row in monthly],
        month_values=[row['total'] for row in monthly], budget_total=budget_total,
        budget_percent=budget_percent, budget_remaining=budget_total - total_spent,
        budget_warning=budget_total and total_spent >= budget_total * .8, goals=goals
    )


@app.route('/expenses')
@login_required
def expenses():
    process_recurring(session['user_id'])
    query, params, filters = _expense_query(session['user_id'], request.args)
    rows = get_db().execute(query, params).fetchall()
    return render_template(
        'expenses.html', expenses=rows, filters=filters,
        total=sum(row['amount'] for row in rows)
    )


@app.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        amount, error = _parse_amount(request.form.get('amount'))
        category = request.form.get('category', 'Other')
        payment = request.form.get('payment_method', 'Cash')
        notes = request.form.get('notes', '').strip()
        expense_date = _valid_date(request.form.get('date'))
        receipt, receipt_error = _save_receipt(request.files.get('receipt'))
        error = error or receipt_error
        if not title:
            error = 'Description is required.'
        elif category not in DEFAULT_CATEGORIES:
            error = 'Select a valid category.'
        elif payment not in PAYMENT_METHODS:
            error = 'Select a valid payment method.'
        if error:
            flash(error, 'error')
        else:
            db = get_db()
            db.execute(
                '''INSERT INTO expense
                   (title, amount, category, payment_method, receipt_filename,
                    notes, date, created_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (title, amount, category, payment, receipt, notes, expense_date,
                 datetime.now().isoformat(), session['user_id'])
            )
            db.commit()
            flash('Expense added successfully.', 'success')
            return redirect(url_for('expenses'))
    return render_template('add_expense.html', today=date.today().isoformat())


@app.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    db = get_db()
    expense = db.execute(
        'SELECT * FROM expense WHERE id = ? AND user_id = ?',
        (expense_id, session['user_id'])
    ).fetchone()
    if not expense:
        abort(404)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        amount, error = _parse_amount(request.form.get('amount'))
        category = request.form.get('category', 'Other')
        payment = request.form.get('payment_method', 'Cash')
        receipt = expense['receipt_filename']
        new_receipt, receipt_error = _save_receipt(request.files.get('receipt'))
        if new_receipt:
            receipt = new_receipt
        error = error or receipt_error
        if not title:
            error = 'Description is required.'
        elif category not in DEFAULT_CATEGORIES or payment not in PAYMENT_METHODS:
            error = 'Select valid category and payment values.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                '''UPDATE expense SET title=?, amount=?, category=?, payment_method=?,
                   receipt_filename=?, notes=?, date=? WHERE id=? AND user_id=?''',
                (title, amount, category, payment, receipt,
                 request.form.get('notes', '').strip(),
                 _valid_date(request.form.get('date'), expense['date']),
                 expense_id, session['user_id'])
            )
            db.commit()
            flash('Expense updated.', 'success')
            return redirect(url_for('expenses'))
    return render_template('edit_expense.html', expense=expense)


@app.post('/expenses/<int:expense_id>/delete')
@login_required
def delete_expense(expense_id):
    db = get_db()
    db.execute('DELETE FROM expense WHERE id = ? AND user_id = ?', (expense_id, session['user_id']))
    db.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))


@app.route('/receipts/<path:filename>')
@login_required
def receipt_file(filename):
    allowed = get_db().execute(
        'SELECT 1 FROM expense WHERE user_id = ? AND receipt_filename = ?',
        (session['user_id'], filename)
    ).fetchone()
    if not allowed:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/income', methods=['GET', 'POST'])
@login_required
def income():
    db = get_db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        amount, error = _parse_amount(request.form.get('amount'))
        source = request.form.get('source', 'Other')
        if not title:
            error = 'Income description is required.'
        elif source not in INCOME_SOURCES:
            error = 'Select a valid income source.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                '''INSERT INTO income (title, amount, source, notes, date, created_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (title, amount, source, request.form.get('notes', '').strip(),
                 _valid_date(request.form.get('date')), datetime.now().isoformat(),
                 session['user_id'])
            )
            db.commit()
            flash('Income added successfully.', 'success')
            return redirect(url_for('income'))
    rows = db.execute(
        'SELECT * FROM income WHERE user_id = ? ORDER BY date DESC, id DESC',
        (session['user_id'],)
    ).fetchall()
    return render_template(
        'income.html', incomes=rows, sources=INCOME_SOURCES,
        total=sum(row['amount'] for row in rows), today=date.today().isoformat()
    )


@app.post('/income/<int:income_id>/delete')
@login_required
def delete_income(income_id):
    db = get_db()
    db.execute('DELETE FROM income WHERE id = ? AND user_id = ?', (income_id, session['user_id']))
    db.commit()
    flash('Income deleted.', 'success')
    return redirect(url_for('income'))


@app.route('/budgets', methods=['GET', 'POST'])
@login_required
def budgets():
    db = get_db()
    selected, _, _ = _month_context(request.values.get('month'))
    month_key = selected.strftime('%Y-%m')
    if request.method == 'POST':
        amount, error = _parse_amount(request.form.get('amount'), 'Budget')
        category = request.form.get('category', 'Overall')
        if category not in ['Overall'] + DEFAULT_CATEGORIES:
            error = 'Select a valid budget category.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                '''INSERT INTO budget (month, category, amount, user_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, month, category)
                   DO UPDATE SET amount = excluded.amount''',
                (month_key, category, amount, session['user_id'])
            )
            db.commit()
            flash('Budget saved.', 'success')
            return redirect(url_for('budgets', month=month_key))
    rows = db.execute(
        'SELECT * FROM budget WHERE user_id = ? AND month = ? ORDER BY category',
        (session['user_id'], month_key)
    ).fetchall()
    spending = dict(db.execute(
        '''SELECT category, SUM(amount) total FROM expense
           WHERE user_id = ? AND substr(date, 1, 7) = ? GROUP BY category''',
        (session['user_id'], month_key)
    ).fetchall())
    return render_template('budgets.html', budgets=rows, spending=spending, month=month_key)


@app.post('/budgets/<int:budget_id>/delete')
@login_required
def delete_budget(budget_id):
    db = get_db()
    db.execute('DELETE FROM budget WHERE id = ? AND user_id = ?', (budget_id, session['user_id']))
    db.commit()
    flash('Budget removed.', 'success')
    return redirect(url_for('budgets', month=request.form.get('month')))


@app.route('/goals', methods=['GET', 'POST'])
@login_required
def goals():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        target, error = _parse_amount(request.form.get('target_amount'), 'Target amount')
        current = request.form.get('current_amount', '0') or '0'
        try:
            current = max(float(current), 0)
        except ValueError:
            current = 0
        if not name:
            error = 'Goal name is required.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                '''INSERT INTO savings_goal
                   (name, target_amount, current_amount, target_date, created_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (name, target, min(current, target), request.form.get('target_date') or None,
                 datetime.now().isoformat(), session['user_id'])
            )
            db.commit()
            flash('Savings goal created.', 'success')
            return redirect(url_for('goals'))
    rows = db.execute(
        'SELECT * FROM savings_goal WHERE user_id = ? ORDER BY id DESC',
        (session['user_id'],)
    ).fetchall()
    return render_template('goals.html', goals=rows)


@app.post('/goals/<int:goal_id>/contribute')
@login_required
def contribute_goal(goal_id):
    amount, error = _parse_amount(request.form.get('amount'), 'Contribution')
    db = get_db()
    goal = db.execute(
        'SELECT * FROM savings_goal WHERE id = ? AND user_id = ?',
        (goal_id, session['user_id'])
    ).fetchone()
    if not goal:
        abort(404)
    if error:
        flash(error, 'error')
    else:
        new_total = min(goal['current_amount'] + amount, goal['target_amount'])
        db.execute('UPDATE savings_goal SET current_amount = ? WHERE id = ?', (new_total, goal_id))
        db.commit()
        flash('Contribution added.', 'success')
    return redirect(url_for('goals'))


@app.post('/goals/<int:goal_id>/delete')
@login_required
def delete_goal(goal_id):
    db = get_db()
    db.execute('DELETE FROM savings_goal WHERE id = ? AND user_id = ?', (goal_id, session['user_id']))
    db.commit()
    flash('Goal removed.', 'success')
    return redirect(url_for('goals'))


@app.route('/recurring', methods=['GET', 'POST'])
@login_required
def recurring():
    db = get_db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        amount, error = _parse_amount(request.form.get('amount'))
        transaction_type = request.form.get('transaction_type', 'Expense')
        frequency = request.form.get('frequency', 'Monthly')
        if not title:
            error = 'Description is required.'
        elif transaction_type not in ['Expense', 'Income'] or frequency not in RECURRING_FREQUENCIES:
            error = 'Select valid recurring transaction values.'
        if error:
            flash(error, 'error')
        else:
            db.execute(
                '''INSERT INTO recurring_transaction
                   (title, amount, transaction_type, category, payment_method, source,
                    frequency, next_due_date, notes, created_at, user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (title, amount, transaction_type, request.form.get('category', 'Other'),
                 request.form.get('payment_method', 'Cash'), request.form.get('source', 'Other'),
                 frequency, _valid_date(request.form.get('next_due_date')),
                 request.form.get('notes', '').strip(), datetime.now().isoformat(),
                 session['user_id'])
            )
            db.commit()
            flash('Recurring transaction created.', 'success')
            return redirect(url_for('recurring'))
    process_recurring(session['user_id'])
    rows = db.execute(
        'SELECT * FROM recurring_transaction WHERE user_id = ? ORDER BY next_due_date',
        (session['user_id'],)
    ).fetchall()
    return render_template(
        'recurring.html', recurring_items=rows, frequencies=RECURRING_FREQUENCIES,
        sources=INCOME_SOURCES, today=date.today().isoformat()
    )


@app.post('/recurring/<int:item_id>/toggle')
@login_required
def toggle_recurring(item_id):
    db = get_db()
    db.execute(
        'UPDATE recurring_transaction SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ? AND user_id = ?',
        (item_id, session['user_id'])
    )
    db.commit()
    return redirect(url_for('recurring'))


@app.post('/recurring/<int:item_id>/delete')
@login_required
def delete_recurring(item_id):
    db = get_db()
    db.execute('DELETE FROM recurring_transaction WHERE id = ? AND user_id = ?', (item_id, session['user_id']))
    db.commit()
    flash('Recurring transaction removed.', 'success')
    return redirect(url_for('recurring'))


@app.route('/reports')
@login_required
def reports():
    today = date.today()
    start = _valid_date(request.args.get('start_date'), today.replace(day=1).isoformat())
    end = _valid_date(request.args.get('end_date'), today.isoformat())
    if start > end:
        start, end = end, start
    db = get_db()
    expenses_rows = db.execute(
        'SELECT * FROM expense WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date',
        (session['user_id'], start, end)
    ).fetchall()
    income_rows = db.execute(
        'SELECT * FROM income WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date',
        (session['user_id'], start, end)
    ).fetchall()
    category_totals = defaultdict(float)
    payment_totals = defaultdict(float)
    daily_totals = defaultdict(float)
    for row in expenses_rows:
        category_totals[row['category']] += row['amount']
        payment_totals[row['payment_method'] or 'Cash'] += row['amount']
        daily_totals[row['date']] += row['amount']
    spent = sum(row['amount'] for row in expenses_rows)
    earned = sum(row['amount'] for row in income_rows)
    days = (datetime.strptime(end, '%Y-%m-%d').date() - datetime.strptime(start, '%Y-%m-%d').date()).days + 1
    highest = max(category_totals, key=category_totals.get) if category_totals else 'No spending'
    return render_template(
        'reports.html', start_date=start, end_date=end, total_spent=spent,
        total_income=earned, net_balance=earned - spent, average_daily=spent / days,
        highest_category=highest, category_labels=list(category_totals),
        category_values=list(category_totals.values()), payment_labels=list(payment_totals),
        payment_values=list(payment_totals.values()), daily_labels=list(daily_totals),
        daily_values=list(daily_totals.values())
    )


@app.route('/export/<file_type>')
@login_required
def export_expenses(file_type):
    query, params, _ = _expense_query(session['user_id'], request.args)
    rows = get_db().execute(query, params).fetchall()
    headers = ['Date', 'Description', 'Category', 'Payment Method', 'Amount', 'Notes']
    values = [[r['date'], r['title'], r['category'], r['payment_method'], r['amount'], r['notes'] or ''] for r in rows]
    if file_type == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(values)
        data = io.BytesIO(output.getvalue().encode('utf-8-sig'))
        return send_file(data, mimetype='text/csv', as_attachment=True, download_name='financehub-expenses.csv')
    if file_type == 'xlsx':
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Expenses'
        sheet.append(headers)
        for row in values:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = cell.font.copy(bold=True)
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name='financehub-expenses.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if file_type == 'pdf':
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        output = io.BytesIO()
        document = SimpleDocTemplate(output, pagesize=landscape(A4), title='FinanceHub Expenses')
        styles = getSampleStyleSheet()
        table_data = [headers] + [[str(cell) for cell in row] for row in values]
        table = Table(table_data, repeatRows=1, colWidths=[70, 130, 80, 95, 70, 180])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), .5, colors.grey),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        document.build([Paragraph('FinanceHub Expense Report', styles['Title']), Spacer(1, 12), table])
        output.seek(0)
        return send_file(output, as_attachment=True, download_name='financehub-expenses.pdf', mimetype='application/pdf')
    abort(404)


@app.route('/api/summary')
@login_required
def api_summary():
    rows = get_db().execute(
        'SELECT category, SUM(amount) total FROM expense WHERE user_id = ? GROUP BY category',
        (session['user_id'],)
    ).fetchall()
    return jsonify({'labels': [r['category'] for r in rows], 'values': [r['total'] for r in rows]})


init_db()

# Mobile API used by the Flutter iPhone and Android applications.
from mobile_api import create_mobile_blueprint

app.register_blueprint(create_mobile_blueprint(app, {
    'get_db': get_db,
    'parse_amount': _parse_amount,
    'valid_date': _valid_date,
    'save_receipt': _save_receipt,
    'process_recurring': process_recurring,
    'categories': DEFAULT_CATEGORIES,
    'payment_methods': PAYMENT_METHODS,
    'income_sources': INCOME_SOURCES,
    'frequencies': RECURRING_FREQUENCIES,
    'upload_folder': UPLOAD_FOLDER,
}))

if __name__ == '__main__':
    app.run(debug=True)
