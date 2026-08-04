# Deployment Guide – FinanceHub

This guide covers deploying FinanceHub to production environments.

## Cloud Deployment Options

### 1. **Heroku** (Simplest for beginners)

```bash
# Install Heroku CLI, then:
heroku login
heroku create your-app-name
git push heroku main
```

**Procfile** (create this file):
```
web: gunicorn app:app
release: python -c "from app import init_db; init_db()"
```

Add Gunicorn to requirements.txt:
```
gunicorn==21.2.0
```

### 2. **Railway.app** (Modern alternative to Heroku)

1. Connect your GitHub repo to Railway
2. Set environment variable: `SECRET_KEY=<your-secret>`
3. Add a Postgres database (optional, currently using SQLite)
4. Deploy automatically on push

### 3. **PythonAnywhere** (Python-specific hosting)

1. Upload files to PythonAnywhere
2. Create a WSGI file pointing to `app:app`
3. Reload the web app

Example **wsgi.py**:
```python
import sys
path = '/home/yourusername/mysite'
sys.path.insert(0, path)
from app import app as application
```

### 4. **DigitalOcean App Platform** (Full control, affordable)

1. Create App Platform app
2. Connect GitHub repo
3. Set port to 8080, set env variables
4. Deploy

### 5. **AWS (Elastic Beanstalk)**

```bash
pip install awsebcli

eb init -p python-3.11 financehub
eb create prod-env
eb deploy
```

## Environment Variables (Production)

Create a `.env` file or set these in your hosting dashboard:

```bash
SECRET_KEY=your-very-secret-key-here-change-this
FLASK_ENV=production
DATABASE_URL=sqlite:///expenses.db  # or PostgreSQL for scale
```

In Python, load them:
```python
import os
from dotenv import load_dotenv
load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
```

## Database Migration (SQLite → PostgreSQL)

For production scale, switch to PostgreSQL:

1. Install `psycopg2`:
   ```bash
   pip install psycopg2-binary
   ```

2. Update connection in `app.py`:
   ```python
   db_url = os.getenv('DATABASE_URL', 'sqlite:///expenses.db')
   app.config['SQLALCHEMY_DATABASE_URI'] = db_url
   ```

3. Use a managed database (Heroku Postgres, Railway Postgres, etc.)

## HTTPS & Security Checklist

- [ ] Use HTTPS (automatic on Railway, Heroku, Render)
- [ ] Set strong `SECRET_KEY` (use `secrets.token_hex(32)`)
- [ ] Add CSRF protection with Flask-WTF (optional for v1)
- [ ] Rate-limit login endpoints
- [ ] Set cookie flags:
  ```python
  app.config['SESSION_COOKIE_SECURE'] = True
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  ```
- [ ] Use environment variables for secrets

## Production WSGI Server

Replace Flask's development server with Gunicorn or uWSGI:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

### Systemd Service (Linux VPS)

Create `/etc/systemd/system/financehub.service`:

```ini
[Unit]
Description=FinanceHub Expense Tracker
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/financehub
ExecStart=/opt/financehub/venv/bin/gunicorn -w 4 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable financehub
sudo systemctl start financehub
```

## Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## SSL Certificate (Let's Encrypt)

```bash
sudo certbot --nginx -d yourdomain.com
```

## Monitoring & Logging

- **Sentry** (error tracking): `pip install sentry-sdk`
- **DataDog** or **New Relic** (APM)
- **ELK Stack** (logging)

## Backup Strategy

- Daily automated backups of SQLite/PostgreSQL
- Use cloud storage (S3, DigitalOcean Spaces)
- Test restores regularly

## Recommended Stack

For production, this configuration works well:

| Component | Recommendation |
|-----------|-----------------|
| Hosting | Railway.app or DigitalOcean |
| WSGI | Gunicorn (4 workers) |
| Database | PostgreSQL (managed) |
| Storage | Cloud CDN (optional for user uploads) |
| SSL | Let's Encrypt / Nginx |
| Monitoring | Sentry |
| Logging | Built-in to platform |

---

**Need help?** Open an issue or check the deployment platform's docs.
