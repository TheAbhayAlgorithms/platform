# RailClub Connect

**Enterprise Membership, Events & Financial Platform for Railway Employees' Institutes**

RailClub Connect is an end-to-end, production-ready platform designed for Indian Railways employees' institutes and clubs. Built using Python Django, it combines enterprise-grade data security (AES-256 field encryption at rest, HMAC blind indexing, Argon2 password hashing) with automated WhatsApp workflows, festival event ticketing, wedding hall reservation management, multi-branch inter-divisional transfers, automated backups, and governance polling.

---

## Technical Architecture & Core Standards

- **Backend Framework**: Python 3.9+, Django 4.2 LTS (server-rendered templates, zero heavyweight JS frameworks)
- **Database**: SQLite (Local development / CI) | PostgreSQL (Production)
- **Timezone**: `Asia/Kolkata` (Indian Standard Time, UTC+05:30)
- **Currency & Numerics**: INR (`₹`), with Indian numbering system format (lakhs/crores) and words conversion
- **Date Standards**: `DD-MM-YYYY` display, ISO-8601 internal storage
- **Cryptographic Security**:
  - **Passwords**: Argon2id via `argon2-cffi`
  - **Sensitive Fields**: AES-256-CBC / Fernet symmetric encryption at rest
  - **Fast Blind Indexing**: Keyed HMAC-SHA256 blind indexing for phone numbers and employee PF IDs
  - **Data Privacy**: Digital Personal Data Protection (DPDP) Act 2023 compliance with explicit opt-in and soft-deletion
- **Messaging Integration**: Modular `WhatsAppProvider` abstraction with mock simulation for test/dev and Meta Cloud API integration for production (Default Sender: `7039145304`)
- **Automated Testing**: 238 comprehensive unit, integration, RBAC, and regression tests (100% passing rate)

---

## Complete Modules Overview (Modules 0 through 18)

### Phase 1: Foundation, Membership & Financial Core (Modules 0–8)
- **Module 0: Project Skeleton & Security Architecture**: Base layout, settings, encryption helpers, security audit test harness.
- **Module 1: Authentication, 2FA & Roles**: Role-based access control (Super Admin, Accountant, Event Manager, Viewer), WhatsApp 2-Step OTP, 20-minute idle session timeout, account lockout.
- **Module 2: Member Management & Privacy**: Member registration, AES-256 encrypted phone & PF IDs, blind index search, family dependents, Excel/CSV bulk import, soft-deletion.
- **Module 3: Membership Plans & Concessions**: Tiered plans (Annual, Half-Yearly, Quarterly), date math, concession discounts, immutable historic fee snapshots.
- **Module 4: Payment Collection & Receipts**: Cash/UPI/NEFT/Cheque recording, automatic status transition (`Due` &rarr; `Active`), ReportLab PDF receipts with Indian currency in words.
- **Module 5: Renewals & Expiry Engine**: One-click rollovers, seamless date extension, automated membership expiry cron sweep with grace periods.
- **Module 6: Member Self-Service Portal**: Mobile OTP passwordless login, responsive dashboard, family view, IDOR-protected PDF receipt downloads.
- **Module 7: Demonstration Seed Data**: Realistic Indian Railways mock data generation across all railway departments and divisions.
- **Module 8: Security Audit & Hardening**: Verification of Argon2, raw database ciphertext inspection, path traversal guards, session security.

### Phase 2: Automation, Reports, Events & Facility Hire (Modules 9–13)
- **Module 9: WhatsApp Notification Engine**: Delivery status tracking, rate-limiting, opt-in enforcement, fallback audit logs.
- **Module 10: Automated WhatsApp Reminders**: Scheduled notifications for upcoming renewal expiries and dues collection.
- **Module 11: Financial & Member Reports**: Daily collection, revenue summary, defaulters aging, and demographic reports with Excel, CSV, and PDF exports.
- **Module 12: Festival Celebrations & Events**: Cultural functions, railway sports meets, ticket tiers, capacity enforcement, QR code verification.
- **Module 13: Wedding & Community Hall Bookings**: Subsidized venue hire, conflict-free slot booking, damage deposit refunds, wedding/puja reservations.

### Phase 3: Governance, Backups, Multi-Branch & Handover (Modules 14–18)
- **Module 14: Polling, Elections & Grievance Feedback**: Secret and open ballot voting for committee elections, strict double-voting prevention, member grievance portal.
- **Module 15: Expense & Budget Tracking**: Institute operational expenditure tracking, budget allocations, vendor management, receipt voucher uploads.
- **Module 16: Automated Data Backups**: Sequential gzipped database snapshot archives (`BKP-YYYY-NNNNN`), cryptographic SHA-256 integrity verification, 30-day retention with 3-backup safety floor.
- **Module 17: Multi-Branch & Inter-Divisional Transfers**: Affiliated Indian Railway divisions directory (`NR-DLI`, `WR-MMCT`, `ER-HWH`, `SCR-SC`, `SR-MAS`, `ECR-DNR`), automated dues clearance audits, printable official No Objection Certificates (`NOC-YYYY-NNNNN`), member portal NOC downloads.
- **Module 18: Final Polish, Production Readiness & Handover**: System health diagnostic probe (`/health/`), runtime telemetry dashboard (`/system-health/`), custom 404/500 error pages, master bootstrap command, security headers (`X-Frame-Options: SAMEORIGIN`, `nosniff`).

---

## Quick Start & Deployment Guide

### 1. Prerequisites
- Python 3.9+
- SQLite3 or PostgreSQL
- Git

### 2. Environment Setup
```bash
# Clone repository
git clone https://github.com/railway-institute/railclub.git
cd platform

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables Configuration
Copy `.env.example` to `.env` and configure keys:
```bash
cp .env.example .env
```
Key variables in `.env`:
```ini
DEBUG=True
SECRET_KEY=railclub-production-secret-key-replace-in-prod
ALLOWED_HOSTS=localhost,127.0.0.1,testserver

FIELD_ENCRYPTION_KEY=your-32-byte-base64-fernet-key
BLIND_INDEX_SALT=your-high-entropy-blind-index-salt-string

WHATSAPP_PROVIDER=mock
WHATSAPP_SENDER_NUMBER=7039145304
```

### 4. Master Bootstrap Command
To automatically apply migrations, seed Indian Railway divisions, populate demo members/plans/staff, and verify security in a single command:
```bash
python manage.py setup_system
```

### 5. Run Automated Tests
Execute the entire test suite across all 18 modules:
```bash
pytest
```
*Expected result: 238 passed.*

### 6. Start Development Server
```bash
python manage.py runserver 127.0.0.1:8000
```
- **Staff Administrative Portal**: `http://127.0.0.1:8000/login/`
- **Member Self-Service Portal**: `http://127.0.0.1:8000/portal/`
- **System Health JSON Probe**: `http://127.0.0.1:8000/health/?full=1`

---

## Demonstration Credentials

| Role | Username / Email | Password | Access Privileges |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `admin@railclub.in` | `Admin@123` | Full administrative authority across all modules, backups, and user management. |
| **Accountant** | `accountant@railclub.in` | `Acct@123` | Dues collection, PDF receipts, financial reports, expenses, transfer approvals. |
| **Event Manager** | `events@railclub.in` | `Events@123` | Festival events, ticket bookings, wedding and community hall reservations. |
| **Read-Only Viewer** | `viewer@railclub.in` | `Viewer@123` | Read-only inspection of member directory, schedules, and reports. |
| **Member Portal** | *Any registered mobile* (e.g. `9811122233`) | OTP via WhatsApp | Self-service status check, PDF receipt downloads, digital NOC downloads, voting. |

*(Note: During development in `mock` provider mode, generated 6-digit WhatsApp OTPs are printed directly to the terminal stdout for convenience).*

---

## Management Commands & Scheduled Crons

| Command | Recommended Schedule | Description |
| :--- | :--- | :--- |
| `python manage.py setup_system` | On deployment | Complete platform initialization, migrations, division seeding, and security audit. |
| `python manage.py expire_memberships` | Daily at 00:05 IST | Checks member plan validity dates and grace periods; transitions overdue members to `EXPIRED`. |
| `python manage.py send_whatsapp_reminders` | Daily at 09:30 IST | Sends automated renewal reminders and dues notices via WhatsApp. |
| `python manage.py run_automated_backup` | Daily at 02:00 IST | Generates gzipped database snapshots (`.json.gz`), calculates SHA-256 hashes, and cleans archives older than 30 days. |
| `python manage.py security_audit` | Post-deploy / Weekly | Verifies raw database ciphertext, Fernet keys, blind index salts, and session configurations. |
| `python manage.py seed_branches` | As needed | Pre-populates Indian Railways zonal institutes and divisional branches. |

---

## Security & Compliance Architecture

1. **Cryptographic Protection at Rest**:
   - Member mobile numbers and railway PF employee numbers are encrypted using AES-256 Fernet (`gAAAAA...` ciphertext in database storage).
   - Database dumps and raw SQL queries never expose plain PII.
2. **Keyed Blind Indexing**:
   - Fast exact-match queries without decrypting the entire database table are powered by keyed HMAC-SHA256 blind indexes.
3. **Directory Traversal Containment**:
   - Backup downloads and document exports enforce strict path resolution: `Path(target).resolve().relative_to(BASE_STORAGE_DIR)` to prevent unauthorized filesystem access.
4. **IDOR Prevention**:
   - Member portal endpoints for receipt and NOC downloads strictly enforce ownership (`member=request.portal_member`).
5. **Session & Transport Protection**:
   - Strict 20-minute idle session timeout.
   - `SECURE_BROWSER_XSS_FILTER = True`, `SECURE_CONTENT_TYPE_NOSNIFF = True`, `X_FRAME_OPTIONS = 'SAMEORIGIN'`, and `CSRF_COOKIE_HTTPONLY = True`.

---

## License & Support

Developed for the Railway Employees' Institute & Club Welfare Administration.
For technical support or deployment assistance, contact: `admin@railclub.in`.
