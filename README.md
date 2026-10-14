# RailClub Connect

**Membership & Events Management Platform for Railway Employees**

RailClub Connect is a comprehensive platform built with Python Django to manage memberships, dues, festival celebrations, and private wedding bookings for a railway employees' institute.

---

## Tech Stack & Architecture
- **Framework**: Python 3.9+, Django 4.2 LTS (server-rendered templates)
- **Database**: SQLite (Local development) / PostgreSQL (Production)
- **Timezone**: `Asia/Kolkata`
- **Currency**: INR (`₹`)
- **Date Format**: `DD-MM-YYYY`
- **Security & Cryptography**:
  - Passwords: Argon2 (`argon2-cffi`)
  - Sensitive Fields: AES-256 Fernet field encryption at rest
  - Phone Lookup: Keyed HMAC-SHA256 blind indexing for exact-match query performance
- **WhatsApp Integration**: Behind a `WhatsAppProvider` abstraction (`MockProvider` for dev/tests, `CloudAPIProvider` for production using sender `7039145304`)
- **Testing**: `pytest` + `pytest-django` + `freezegun`

---

## Directory Structure
```
platform/
├── core/                   # Core shared utilities, cryptography, base models & context
├── railclub/               # Project configuration & settings
├── templates/              # Server-rendered HTML templates (Clean & Minimal)
├── static/css/             # Plain CSS styling (No heavy JS frameworks)
├── .env.example            # Environment variables template
├── pytest.ini              # Pytest Django configuration
├── requirements.txt        # Production & development dependencies
└── manage.py
```

---

## Getting Started

### 1. Prerequisites
- Python 3.9+
- Git

### 2. Virtual Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Ensure `FIELD_ENCRYPTION_KEY` and `BLIND_INDEX_SALT` are properly set.

### 4. Run Migrations
```bash
python manage.py migrate
```

### 5. Run Automated Tests
```bash
pytest
```

### 6. Start the Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` or `http://127.0.0.1:8000/health/`.
