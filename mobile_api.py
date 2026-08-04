import csv
import io
import os
from collections import defaultdict
from datetime import date, datetime
from functools import wraps

from flask import Blueprint, abort, jsonify, request, send_file
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash


def create_mobile_blueprint(app, dependencies):
    api = Blueprint('mobile_api', __name__, url_prefix='/api/mobile')
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='financehub-mobile')
    get_db = dependencies['get_db']
    parse_amount = dependencies['parse_amount']
    valid_date = dependencies['valid_date']
    save_receipt = dependencies['save_receipt']
    process_recurring = dependencies['process_recurring']
    categories = dependencies['categories']
    payment_methods = dependencies['payment_methods']
    income_sources = dependencies['income_sources']
    frequencies = dependencies['frequencies']
    upload_folder = dependencies['upload_folder']

    def token_for(user_id):
        return serializer.dumps({'user_id': user_id})

    def resolve_token():
        header = request.headers.get('Authorization', '')
        token = header.removeprefix('Bearer ').strip()
        if not token:
            return None
        try:
            return int(serializer.loads(token, max_age=60 * 60 * 24 * 30)['user_id'])
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
            return None

    def mobile_auth(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = resolve_token()
            if not user_id:
                return jsonify({'error': 'Authentication required.'}), 401
            user = get_db().execute('SELECT * FROM user WHERE id = ?', (user_id,)).fetchone()
            if not user:
                return jsonify({'error': 'Account not found.'}), 401
            return view(user_id, *args, **kwargs)
        return wrapped

    def rows(items):
        return [dict(item) for item in items]

    def body():
        return request.get_json(silent=True) or request.form

    @api.after_request
    def mobile_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        return response

    @api.route('/config')
    def config():
        return jsonify({
            'categories': categories, 'payment_methods': payment_methods,
            'income_sources': income_sources, 'frequencies': frequencies
        })

    @api.post('/register')
    def register():
        data = body()
        username = str(data.get('username', '')).strip()
        email = str(data.get('email', '')).strip().lower()
        password = str(data.get('password', ''))
        if not username or not email or len(password) < 6:
            return jsonify({'error': 'Enter username, email and a password of at least 6 characters.'}), 400
        db = get_db()
        if db.execute('SELECT 1 FROM user WHERE username = ? OR email = ?', (username, email)).fetchone():
            return jsonify({'error': 'Username or email already registered.'}), 409
        cursor = db.execute(
            'INSERT INTO user (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
            (username, email, generate_password_hash(password), datetime.now().isoformat())
        )
        db.commit()
        return jsonify({'token': token_for(cursor.lastrowid), 'user': {'id': cursor.lastrowid, 'username': username, 'email': email}}), 201

    @api.post('/login')
    def login():
        data = body()
        identity = str(data.get('identity', data.get('username', ''))).strip()
        user = get_db().execute(
            'SELECT * FROM user WHERE username = ? OR email = ?', (identity, identity.lower())
        ).fetchone()
        if not user or not check_password_hash(user['password_hash'], str(data.get('password', ''))):
            return jsonify({'error': 'Invalid username/email or password.'}), 401
        return jsonify({'token': token_for(user['id']), 'user': {'id': user['id'], 'username': user['username'], 'email': user['email']}})

    @api.get('/me')
    @mobile_auth
    def me(user_id):
        user = get_db().execute('SELECT id, username, email, created_at FROM user WHERE id = ?', (user_id,)).fetchone()
        return jsonify(dict(user))

    @api.delete('/account')
    @mobile_auth
    def delete_account(user_id):
        data = body()
        user = get_db().execute('SELECT * FROM user WHERE id = ?', (user_id,)).fetchone()
        if not check_password_hash(user['password_hash'], str(data.get('password', ''))):
            return jsonify({'error': 'Password is incorrect.'}), 403
        db = get_db()
        db.execute('DELETE FROM user WHERE id = ?', (user_id,))
        db.commit()
        return jsonify({'message': 'Account and financial data deleted.'})

    @api.get('/dashboard')
    @mobile_auth
    def dashboard(user_id):
        process_recurring(user_id)
        month = request.args.get('month') or date.today().strftime('%Y-%m')
        try:
            selected = datetime.strptime(month, '%Y-%m')
        except ValueError:
            selected = datetime(date.today().year, date.today().month, 1)
            month = selected.strftime('%Y-%m')
        db = get_db()
        expenses = db.execute(
            'SELECT * FROM expense WHERE user_id = ? AND substr(date, 1, 7) = ? ORDER BY date DESC, id DESC',
            (user_id, month)
        ).fetchall()
        incomes = db.execute(
            'SELECT * FROM income WHERE user_id = ? AND substr(date, 1, 7) = ? ORDER BY date DESC',
            (user_id, month)
        ).fetchall()
        budgets = db.execute('SELECT * FROM budget WHERE user_id = ? AND month = ?', (user_id, month)).fetchall()
        goals = db.execute('SELECT * FROM savings_goal WHERE user_id = ? ORDER BY id DESC LIMIT 3', (user_id,)).fetchall()
        spent = sum(row['amount'] for row in expenses)
        earned = sum(row['amount'] for row in incomes)
        category = defaultdict(float)
        payments = defaultdict(float)
        for row in expenses:
            category[row['category']] += row['amount']
            payments[row['payment_method'] or 'Cash'] += row['amount']
        overall = next((row['amount'] for row in budgets if row['category'] == 'Overall'), 0)
        budget = overall or sum(row['amount'] for row in budgets if row['category'] != 'Overall')
        trend = db.execute(
            '''SELECT substr(date,1,7) month, SUM(amount) total FROM expense
               WHERE user_id = ? GROUP BY month ORDER BY month DESC LIMIT 6''', (user_id,)
        ).fetchall()[::-1]
        return jsonify({
            'month': month, 'month_name': selected.strftime('%B %Y'), 'income': earned,
            'expenses': spent, 'balance': earned - spent, 'transaction_count': len(expenses),
            'budget': budget, 'budget_used_percent': (spent / budget * 100 if budget else 0),
            'recent_expenses': rows(expenses[:5]), 'goals': rows(goals),
            'category_chart': {'labels': list(category), 'values': list(category.values())},
            'payment_chart': {'labels': list(payments), 'values': list(payments.values())},
            'trend_chart': {'labels': [r['month'] for r in trend], 'values': [r['total'] for r in trend]}
        })

    @api.route('/expenses', methods=['GET', 'POST'])
    @mobile_auth
    def expenses(user_id):
        db = get_db()
        if request.method == 'GET':
            query = 'SELECT * FROM expense WHERE user_id = ?'
            params = [user_id]
            for key in ['category', 'payment_method']:
                value = request.args.get(key, '').strip()
                if value:
                    query += f' AND {key} = ?'
                    params.append(value)
            search = request.args.get('search', '').strip()
            if search:
                query += ' AND (title LIKE ? OR notes LIKE ?)'
                params.extend([f'%{search}%', f'%{search}%'])
            for key, operator in [('start_date', '>='), ('end_date', '<=')]:
                value = request.args.get(key, '').strip()
                if value:
                    query += f' AND date {operator} ?'
                    params.append(valid_date(value))
            query += ' ORDER BY date DESC, id DESC'
            return jsonify(rows(db.execute(query, params).fetchall()))
        data = body()
        amount, error = parse_amount(data.get('amount'))
        title = str(data.get('title', '')).strip()
        category = data.get('category', 'Other')
        payment = data.get('payment_method', 'Cash')
        receipt, receipt_error = save_receipt(request.files.get('receipt'))
        error = error or receipt_error
        if not title:
            error = 'Description is required.'
        if category not in categories or payment not in payment_methods:
            error = 'Invalid category or payment method.'
        if error:
            return jsonify({'error': error}), 400
        cursor = db.execute(
            '''INSERT INTO expense
               (title, amount, category, payment_method, receipt_filename, notes, date, created_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (title, amount, category, payment, receipt, data.get('notes', ''),
             valid_date(data.get('date')), datetime.now().isoformat(), user_id)
        )
        db.commit()
        item = db.execute('SELECT * FROM expense WHERE id = ?', (cursor.lastrowid,)).fetchone()
        return jsonify(dict(item)), 201

    @api.route('/expenses/<int:item_id>', methods=['PUT', 'DELETE'])
    @mobile_auth
    def expense_item(user_id, item_id):
        db = get_db()
        existing = db.execute('SELECT * FROM expense WHERE id = ? AND user_id = ?', (item_id, user_id)).fetchone()
        if not existing:
            abort(404)
        if request.method == 'DELETE':
            db.execute('DELETE FROM expense WHERE id = ? AND user_id = ?', (item_id, user_id))
            db.commit()
            return jsonify({'message': 'Expense deleted.'})
        data = body()
        amount, error = parse_amount(data.get('amount', existing['amount']))
        if error:
            return jsonify({'error': error}), 400
        db.execute(
            '''UPDATE expense SET title=?, amount=?, category=?, payment_method=?, notes=?, date=?
               WHERE id=? AND user_id=?''',
            (data.get('title', existing['title']), amount, data.get('category', existing['category']),
             data.get('payment_method', existing['payment_method']), data.get('notes', existing['notes']),
             valid_date(data.get('date'), existing['date']), item_id, user_id)
        )
        db.commit()
        return jsonify(dict(db.execute('SELECT * FROM expense WHERE id = ?', (item_id,)).fetchone()))

    @api.get('/receipts/<path:filename>')
    @mobile_auth
    def receipt(user_id, filename):
        if not get_db().execute('SELECT 1 FROM expense WHERE user_id = ? AND receipt_filename = ?', (user_id, filename)).fetchone():
            abort(404)
        from flask import send_from_directory
        return send_from_directory(upload_folder, filename)

    @api.route('/income', methods=['GET', 'POST'])
    @mobile_auth
    def income(user_id):
        db = get_db()
        if request.method == 'GET':
            return jsonify(rows(db.execute('SELECT * FROM income WHERE user_id = ? ORDER BY date DESC, id DESC', (user_id,)).fetchall()))
        data = body()
        amount, error = parse_amount(data.get('amount'))
        title = str(data.get('title', '')).strip()
        if not title:
            error = 'Description is required.'
        if error:
            return jsonify({'error': error}), 400
        cursor = db.execute(
            'INSERT INTO income (title,amount,source,notes,date,created_at,user_id) VALUES (?,?,?,?,?,?,?)',
            (title, amount, data.get('source', 'Other'), data.get('notes', ''), valid_date(data.get('date')),
             datetime.now().isoformat(), user_id)
        )
        db.commit()
        return jsonify(dict(db.execute('SELECT * FROM income WHERE id=?', (cursor.lastrowid,)).fetchone())), 201

    @api.delete('/income/<int:item_id>')
    @mobile_auth
    def delete_income(user_id, item_id):
        db = get_db(); db.execute('DELETE FROM income WHERE id=? AND user_id=?', (item_id, user_id)); db.commit()
        return jsonify({'message': 'Income deleted.'})

    @api.route('/budgets', methods=['GET', 'POST'])
    @mobile_auth
    def budgets(user_id):
        db = get_db(); data = body(); month = request.args.get('month') or data.get('month') or date.today().strftime('%Y-%m')
        if request.method == 'GET':
            return jsonify(rows(db.execute('SELECT * FROM budget WHERE user_id=? AND month=? ORDER BY category', (user_id, month)).fetchall()))
        amount, error = parse_amount(data.get('amount'), 'Budget')
        if error: return jsonify({'error': error}), 400
        category = data.get('category', 'Overall')
        db.execute('''INSERT INTO budget(month,category,amount,user_id) VALUES(?,?,?,?)
                      ON CONFLICT(user_id,month,category) DO UPDATE SET amount=excluded.amount''',
                   (month, category, amount, user_id)); db.commit()
        return jsonify({'message': 'Budget saved.'}), 201

    @api.delete('/budgets/<int:item_id>')
    @mobile_auth
    def delete_budget(user_id, item_id):
        db=get_db();db.execute('DELETE FROM budget WHERE id=? AND user_id=?',(item_id,user_id));db.commit();return jsonify({'message':'Budget deleted.'})

    @api.route('/goals', methods=['GET', 'POST'])
    @mobile_auth
    def goals(user_id):
        db=get_db()
        if request.method=='GET': return jsonify(rows(db.execute('SELECT * FROM savings_goal WHERE user_id=? ORDER BY id DESC',(user_id,)).fetchall()))
        data=body();target,error=parse_amount(data.get('target_amount'),'Target amount');name=str(data.get('name','')).strip()
        if not name: error='Goal name is required.'
        if error:return jsonify({'error':error}),400
        current=max(float(data.get('current_amount',0) or 0),0)
        cursor=db.execute('INSERT INTO savings_goal(name,target_amount,current_amount,target_date,created_at,user_id) VALUES(?,?,?,?,?,?)',(name,target,min(current,target),data.get('target_date') or None,datetime.now().isoformat(),user_id));db.commit()
        return jsonify(dict(db.execute('SELECT * FROM savings_goal WHERE id=?',(cursor.lastrowid,)).fetchone())),201

    @api.post('/goals/<int:item_id>/contribute')
    @mobile_auth
    def contribute(user_id,item_id):
        db=get_db();goal=db.execute('SELECT * FROM savings_goal WHERE id=? AND user_id=?',(item_id,user_id)).fetchone()
        if not goal:abort(404)
        amount,error=parse_amount(body().get('amount'),'Contribution')
        if error:return jsonify({'error':error}),400
        db.execute('UPDATE savings_goal SET current_amount=? WHERE id=?',(min(goal['current_amount']+amount,goal['target_amount']),item_id));db.commit();return jsonify({'message':'Contribution added.'})

    @api.delete('/goals/<int:item_id>')
    @mobile_auth
    def delete_goal(user_id,item_id):
        db=get_db();db.execute('DELETE FROM savings_goal WHERE id=? AND user_id=?',(item_id,user_id));db.commit();return jsonify({'message':'Goal deleted.'})

    @api.route('/recurring', methods=['GET', 'POST'])
    @mobile_auth
    def recurring(user_id):
        process_recurring(user_id);db=get_db()
        if request.method=='GET':return jsonify(rows(db.execute('SELECT * FROM recurring_transaction WHERE user_id=? ORDER BY next_due_date',(user_id,)).fetchall()))
        data=body();amount,error=parse_amount(data.get('amount'));title=str(data.get('title','')).strip()
        if not title:error='Description is required.'
        if error:return jsonify({'error':error}),400
        cursor=db.execute('''INSERT INTO recurring_transaction(title,amount,transaction_type,category,payment_method,source,frequency,next_due_date,notes,created_at,user_id)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(title,amount,data.get('transaction_type','Expense'),data.get('category','Other'),data.get('payment_method','Cash'),data.get('source','Other'),data.get('frequency','Monthly'),valid_date(data.get('next_due_date')),data.get('notes',''),datetime.now().isoformat(),user_id));db.commit()
        return jsonify(dict(db.execute('SELECT * FROM recurring_transaction WHERE id=?',(cursor.lastrowid,)).fetchone())),201

    @api.post('/recurring/<int:item_id>/toggle')
    @mobile_auth
    def toggle_recurring(user_id,item_id):
        db=get_db();db.execute('UPDATE recurring_transaction SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND user_id=?',(item_id,user_id));db.commit();return jsonify({'message':'Recurring status updated.'})

    @api.delete('/recurring/<int:item_id>')
    @mobile_auth
    def delete_recurring(user_id,item_id):
        db=get_db();db.execute('DELETE FROM recurring_transaction WHERE id=? AND user_id=?',(item_id,user_id));db.commit();return jsonify({'message':'Recurring item deleted.'})

    @api.get('/reports')
    @mobile_auth
    def reports(user_id):
        start=valid_date(request.args.get('start_date'),date.today().replace(day=1).isoformat());end=valid_date(request.args.get('end_date'),date.today().isoformat())
        db=get_db();expense_rows=db.execute('SELECT * FROM expense WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date',(user_id,start,end)).fetchall();income_rows=db.execute('SELECT * FROM income WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date',(user_id,start,end)).fetchall()
        category=defaultdict(float);payment=defaultdict(float);daily=defaultdict(float)
        for row in expense_rows:category[row['category']]+=row['amount'];payment[row['payment_method'] or 'Cash']+=row['amount'];daily[row['date']]+=row['amount']
        spent=sum(r['amount'] for r in expense_rows);earned=sum(r['amount'] for r in income_rows)
        return jsonify({'start_date':start,'end_date':end,'total_spent':spent,'total_income':earned,'balance':earned-spent,'top_category':max(category,key=category.get) if category else 'No spending','category_chart':{'labels':list(category),'values':list(category.values())},'payment_chart':{'labels':list(payment),'values':list(payment.values())},'daily_chart':{'labels':list(daily),'values':list(daily.values())}})

    @api.get('/export/<file_type>')
    @mobile_auth
    def export(user_id,file_type):
        expense_rows=get_db().execute('SELECT * FROM expense WHERE user_id=? ORDER BY date DESC',(user_id,)).fetchall();headers=['Date','Description','Category','Payment Method','Amount','Notes'];values=[[r['date'],r['title'],r['category'],r['payment_method'],r['amount'],r['notes'] or ''] for r in expense_rows]
        if file_type=='csv':
            output=io.StringIO();writer=csv.writer(output);writer.writerow(headers);writer.writerows(values);return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name='financehub-expenses.csv')
        if file_type=='xlsx':
            from openpyxl import Workbook
            workbook=Workbook();sheet=workbook.active;sheet.append(headers)
            for row in values:sheet.append(row)
            output=io.BytesIO();workbook.save(output);output.seek(0);return send_file(output,as_attachment=True,download_name='financehub-expenses.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        if file_type=='pdf':
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape,A4
            from reportlab.platypus import SimpleDocTemplate,Table,TableStyle
            output=io.BytesIO();document=SimpleDocTemplate(output,pagesize=landscape(A4));table=Table([headers]+[[str(v) for v in row] for row in values],repeatRows=1);table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#667eea')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.5,colors.grey),('FONTSIZE',(0,0),(-1,-1),8)]));document.build([table]);output.seek(0);return send_file(output,as_attachment=True,download_name='financehub-expenses.pdf',mimetype='application/pdf')
        abort(404)

    return api
