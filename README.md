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
├── accounts/               # Module 1: Admin authentication, 2FA OTP, roles & user management
├── members/                # Module 2: Member management, family dependents, bulk import, soft deletion
├── plans/                  # Module 3: Membership plans, validity math, concessions, fee immutability
├── payments/               # Module 4: Payments, dues, PDF receipts, cancellations & refunds
├── core/                   # Core shared utilities, cryptography, number to words, base models
├── railclub/               # Project configuration & settings
├── templates/              # Server-rendered HTML templates (Clean & Minimal)
│   ├── accounts/           # Login, OTP verification, dashboard, user management
│   ├── members/            # Directory, member detail, add/edit, soft delete, bulk import
│   ├── plans/              # Plans list, create/edit, concessions, member plan assignment
│   ├── payments/           # Transactions list, record payment, receipt detail, cancel, adjust
│   ├── base.html           # Minimal base layout
│   └── home.html           # Landing page
├── static/css/             # Plain CSS styling (No heavy JS frameworks)
├── .env.example            # Environment variables template
├── pytest.ini              # Pytest Django configuration
├── requirements.txt        # Production & development dependencies
└── manage.py
```

---

## Module 1: Authentication & Access Control

### Features Built:
1. **Admin Login & 2-Step OTP Verification**:
   - Secure login with username and password.
   - 2-Step verification (OTP) sent to the admin's registered mobile via WhatsApp (mock provider logs to console/db).
   - Single-use 6-digit OTP with 5-minute expiration, max 3 attempts, and cryptographically hashed storage in DB.
2. **Brute-Force Protection & Lockout**:
   - Consecutive failed password attempts are tracked.
   - Account is locked for 15 minutes after 5 failed attempts.
3. **Session Idle Timeout**:
   - Enforces strict 20-minute idle session timeout.
   - Inactive sessions are automatically invalidated with redirection to login.
4. **Role-Based Access Control (RBAC)**:
   - 4 Roles: `Super Admin`, `Accountant`, `Event Manager`, `Viewer`.
   - Role decorators (`@role_required`, `@super_admin_required`) protecting all administrative views.
   - Super Admin only can create, edit, disable, or reset passwords for admin staff.
5. **Password Management**:
   - Change password for authenticated admins.
   - Forgot/Reset password via secure cryptographic one-time token.

### Pre-Seeded Demo Accounts (Fake numbers):
| Username | Password | Role | Phone (2FA) |
| :--- | :--- | :--- | :--- |
| `superadmin` | `Admin@RailClub2026!` | Super Admin | `+919876543210` |
| `accountant` | `Acct@RailClub2026!` | Accountant | `+919876543211` |
| `eventmanager` | `Event@RailClub2026!` | Event Manager | `+919876543212` |
| `viewer` | `View@RailClub2026!` | Viewer | `+919876543213` |

---

## Module 2: Member Management

### Features Built:
1. **Member Profiles & Data Security**:
   - Auto-generated sequential membership ID (`RC-YYYY-XXXXX`).
   - Sensitive contact number and Railway Employee/PF ID encrypted at rest (AES-256 Fernet).
   - Keyed HMAC-SHA256 blind indexes allowing sub-millisecond phone and employee ID exact-match queries without decrypting entire tables.
   - Indian mobile number normalization (`+91XXXXXXXXXX`) with duplicate prevention.
   - WhatsApp opt-in flag for DPDP Act compliance.
2. **Statuses & Soft Deletion**:
   - Status tracking: `Active`, `Due`, `Expired`, `Suspended`, `Removed`.
   - Soft-delete retention: only Super Admin can remove members; records retain full audit trail and reason, with restoration support.
3. **Family & Dependent Members**:
   - Add and manage dependents (Spouse, Son, Daughter, Parents).
4. **Search, Filtering & Pagination**:
   - Search by name, phone (via blind index), membership ID, or employee ID.
   - Filter by status and railway department with pagination.
5. **Bulk Import (Excel / CSV)**:
   - Supports `.csv` and `.xlsx` (via `openpyxl`).
   - Dry-run validation mode with row-by-row error detection and duplicate phone detection.

---

## Module 3: Membership Plans & Fee Setup

### Features Built:
1. **Membership Plans & Validity Rules**:
   - Configure plans: Annual (12 months), Half-Yearly (6 months), Quarterly (3 months), Festival Special (1 month), and Custom.
   - Exact calendar validity end-date calculation handling month-ends (e.g. 31-Jan to 28-Feb) and leap years (e.g. 29-Feb).
   - Configurable grace period (days) and late fee policies (None, Flat amount, or Per-Day rate).
   - Plan deactivation: deactivated plans cannot be newly assigned to members.
2. **Concessions & Discounts**:
   - Category-based deductions: Percentage discount (e.g., 50% for retired railway employees) or Flat amount discount (e.g., ₹300 for senior citizens).
3. **Fee Immutability & Member Assignment**:
   - Snapshotting: When a plan is assigned to a member, the base fee and final payable amount are recorded immutably. Future plan fee changes never retroactively alter already-assigned fees.
   - Automatic suggestion of start date based on previous plan expiry.

---

## Module 4: Payments & Dues

### Features Built:
1. **Payment Collection & Recording**:
   - Record payments: Cash, UPI / QR Code, Bank Transfer (NEFT/RTGS), Cheque.
   - Transaction reference number tracking (UTR, Cheque number).
   - Partial payments, running balance, and excess payment handling.
2. **Automatic Member Status Transitions**:
   - Automatically transitions member status from `Due` to `Active` once the full due amount is settled.
   - If a payment is cancelled, dues are restored and member transitions back to `Due`.
3. **PDF Receipt Generation**:
   - Official, printable PDF receipt generated using `reportlab`.
   - Unique sequential receipt numbers (`RCP-YYYY-XXXXX`).
   - Institute header, member details, plan validity, and amount in numbers and Indian words (e.g., "Rupees Three Thousand Only").
4. **Cancellation Audit & Financial Adjustments**:
   - Payments can only be cancelled with a mandatory audit reason. The original record is preserved.
   - Supports financial adjustments, refunds, and late fee waivers.
5. **Role Restrictions**:
   - Strictly restricted to `Accountant` and `Super Admin` roles. Viewers and Event Managers are read-only.

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

### 4. Run Migrations & Seed Demo Data
```bash
python manage.py migrate
python manage.py seed_accounts
python manage.py seed_members
python manage.py seed_plans
python manage.py seed_payments
```

### 5. Run Automated Tests
```bash
pytest
```

### 6. Start the Development Server
```bash
python manage.py runserver
```
Visit `http://127.0.0.1:8000/login/`. During login, check the terminal console for the printed Mock WhatsApp OTP code (e.g. `[MOCK WHATSAPP OTP] To: +919876543210 | OTP: 123456`).
