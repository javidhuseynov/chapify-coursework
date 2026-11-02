# Chapify

![Tests](https://github.com/javidhuseynov/chapify-coursework/actions/workflows/tests.yml/badge.svg)

Self-service printing information system with integrated micro-payment functionality
(bachelor's thesis project, Vilnius University Kaunas Faculty).

A user uploads a document, chooses print settings, sees the calculated price, pays through a
payment gateway and follows the print job until it is printed. Administrators monitor the
print queue, payments, printers and the audit log.

- **Payment:** a simulated external gateway ("Chapify Pay - test mode", `mockgateway` app).
  Chapify only accepts payment results that carry the gateway's valid HMAC-SHA256 signature.
- **Printing:** a simulated print server (queue + `run_print_simulator` command, or a button on
  the admin dashboard). No physical printer is needed.
- **Stack:** Python 3.12+, Django 6.0, Django REST Framework, SQLite, Bootstrap 5.

The course-work version of June 2026 is tagged `coursework-baseline`; everything after that tag
is bachelor's-thesis work (`git log coursework-baseline..HEAD`).

---

## 1. Local setup (Windows 11, PowerShell)

Requirements: Git and **Python 3.12 or newer** (`python --version`).

### First time only

```powershell
git clone https://github.com/javidhuseynov/chapify-coursework.git
cd chapify-coursework
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env        # then edit .env and replace the <placeholders>
python manage.py migrate
python manage.py createsuperuser   # this account becomes a Chapify administrator
```

If activation is blocked ("running scripts is disabled"), run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

`.env` is optional for local development (safe development defaults are used), but required for
any shared or hosted environment. Never commit it.

### Every session

```powershell
cd chapify-coursework
.\venv\Scripts\Activate.ps1
python manage.py runserver
```

Open http://127.0.0.1:8000/ (application) and http://127.0.0.1:8000/admin/ (Django admin).

Optional second terminal (activate the venv there too) to process the print queue automatically:

```powershell
python manage.py run_print_simulator              # Ctrl+C to stop
python manage.py run_print_simulator --fail-rate 0.3   # 30 % of jobs fail
```

### After pulling new changes

```powershell
git status                       # must be clean before pulling
git pull --ff-only
pip install -r requirements.txt  # only needed if requirements.txt changed
python manage.py migrate         # applies new database migrations, if any
python manage.py test            # all tests must pass
```

Do **not** run `makemigrations` during normal setup: migrations are part of the repository.

---

## 2. Demonstration walkthrough

1. Register a user (or log in) and choose **New Request**.
2. Upload a PDF, DOCX or TXT file (max 5 MB), enter the page count and print settings.
3. On the payment page press **Pay**. You are sent to the Chapify Pay test checkout.
4. Choose **Approve payment** (or **Decline** to see the retry path).
5. Back in Chapify, the request is *Payment confirmed* and the print job is *Queued*.
6. Log in as the administrator, open **Admin Dashboard** and press **Process next print job**
   (tick *Simulate printer failure* to demonstrate a failed job), or run `run_print_simulator`.
7. The user's request becomes *Completed* (or *Failed*); the uploaded file has been deleted.
8. The audit log (dashboard, report page, Django admin) shows every step.

## 3. Request lifecycle

```
AWAITING_PAYMENT --(gateway: APPROVED)--> PAYMENT_CONFIRMED --(printed)--> COMPLETED
       |   ^                                        |
       |   |(user retries payment)                  +--(printer error)--> FAILED
       |   |
       +--(gateway: DECLINED)--> PAYMENT_REJECTED
       |                               |
       +-------(user cancels / not paid within retention period)------> CANCELLED
```

Print jobs: `QUEUED -> IN_PROGRESS -> COMPLETED | FAILED`. The uploaded file is kept until the
request reaches `COMPLETED`, `FAILED` or `CANCELLED`, then deleted.

Price (thesis §4.5): `pages x copies x 0.10 EUR x colour (1.0/2.0) x paper (A4 1.0 / A3 1.8) x duplex (1.0/0.9)`,
calculated with exact decimals and rounded half-up to cents (`printing/pricing.py`).

## 4. Payment security design

1. When the user presses **Pay**, Chapify creates a `PaymentTransaction` (status `INITIATED`,
   unique UUID `reference`) and redirects to the gateway with a **signed checkout session**
   (reference, amount, currency, return URL). Changing the amount in the URL breaks the signature.
2. The gateway returns a **signed notification** (reference, amount, currency, APPROVED/DECLINED,
   gateway transaction id). It is delivered to `/payments/return/` (browser) and can also be
   delivered server-to-server to `/payments/callback/` (webhook).
3. Chapify accepts the notification only if: the signature is valid, it is at most 15 minutes old,
   the reference exists and is still `INITIATED`, and amount and currency match.
4. Status changes are atomic conditional updates; a replayed notification is recognised as a
   duplicate; a database constraint allows at most one confirmed payment per request.
5. Refused notifications are written to the audit log (`PAYMENT_NOTIFICATION_REFUSED`).

No endpoint lets a user confirm a payment. Chapify never sees card data.

## 5. Roles

- **User**: own requests only (other users' requests return HTTP 404).
- **Administrator**: `Profile.role = ADMIN`. Accounts created with `createsuperuser` get this role
  automatically; others can be promoted in Django admin -> Profiles. Used for the admin pages and
  the `/api/admin/*` endpoints. (The Django admin site itself also needs Django's *staff status*.)

## 6. REST API

Authentication: session, or token (`Authorization: Token <token>`).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/token/` | Get a token (`username`, `password`) |
| GET | `/api/my/requests/` | Own print requests (`?status=`, `?q=`) |
| GET | `/api/my/requests/<id>/` | One own request |
| GET | `/api/my/payments/` | Own payment attempts |
| GET | `/api/my/print-jobs/` | Own print jobs |
| POST | `/api/requests/create/` | Create a request (multipart: `file`, `document_pages`, `copies`, `color_mode` BW/COLOR, `paper_format` A4/A3, `duplex_mode` ONE_SIDED/DOUBLE_SIDED) |
| POST | `/api/requests/<id>/payment/` | Start a payment; returns `checkout_url` for the payer |
| POST | `/api/requests/<id>/cancel/` | Cancel an unpaid request |
| POST | `/payments/callback/` | Gateway webhook (form field or JSON `notification`; no login, signature-verified) |
| GET | `/api/admin/summary/`, `requests/`, `transactions/`, `print-jobs/`, `printers/`, `audit-logs/` | Administrator only |

PowerShell examples (`curl.exe`, placeholders in `<...>`):

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/auth/token/ -d "username=<user>" -d "password=<password>"
curl.exe -H "Authorization: Token <token>" -F "file=@report.pdf" -F "document_pages=2" -F "copies=2" `
  -F "color_mode=BW" -F "paper_format=A4" -F "duplex_mode=ONE_SIDED" http://127.0.0.1:8000/api/requests/create/
curl.exe -H "Authorization: Token <token>" -X POST http://127.0.0.1:8000/api/requests/<id>/payment/
```

Open the returned `checkout_url` in a browser to approve or decline the payment.

## 7. Management commands

| Command | Purpose |
|---|---|
| `python manage.py run_print_simulator [--once] [--fail-rate 0.2] [--seconds-per-page 0.5]` | Simulated print server |
| `python manage.py cleanup_documents [--hours 24] [--dry-run]` | Retention policy: expire unpaid requests, delete abandoned uploads |

## 8. Tests

```powershell
python manage.py test
```

GitHub Actions runs the same checks (`check`, `makemigrations --check`, `test`) automatically on
every push to `main` and every pull request, on Windows and Linux with Python 3.12 and 3.13
(`.github/workflows/tests.yml`). Results: repository → **Actions** tab.

Test modules (`printing/tests/`): pricing and signatures, workflow rules, payment security
(tampering, replay, amount mismatch, expiry, no self-confirmation), print queue and retention,
access control (IDOR, authentication, administrator RBAC).

## 9. Project structure

```
chapify/            settings (env-driven), root URLs, .env loader
printing/           Chapify application
  models.py         data model
  pricing.py        price formula (Decimal)
  services.py       workflow rules: status transitions, payments, print jobs, retention
  payments.py       Chapify side of the gateway integration (checkout session, notification check)
  permissions.py    administrator rule (RBAC)
  views.py          web pages and REST API
  management/       run_print_simulator, cleanup_documents
  tests/            automated tests
mockgateway/        simulated external payment gateway (test-mode checkout page)
  signing.py        signed message format (HMAC-SHA256), shared with Chapify
private_media/      uploaded documents (git-ignored, never served over HTTP)
```
