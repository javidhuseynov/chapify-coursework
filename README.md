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

## 1. Local setup (Windows, Command Prompt)

Requirements: Git and **Python 3.12 or newer** (`python --version`).
Type each command on its own line.

### First time only

```bat
git clone https://github.com/javidhuseynov/chapify-coursework.git
cd chapify-coursework
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
notepad .env
python manage.py migrate
python manage.py createsuperuser
```

In `.env`, replace each `<placeholder>` with a random value from
`python -c "import secrets; print(secrets.token_urlsafe(50))"`. `.env` is never committed.
The account created with `createsuperuser` becomes a Chapify administrator.

### Every session

```bat
cd chapify-coursework
venv\Scripts\activate.bat
python manage.py runserver
```

The prompt shows `(venv)` when the environment is active. Open http://127.0.0.1:8000/
(application) and http://127.0.0.1:8000/admin/ (Django admin).

Optional second cmd window (activate the venv there too) to process the print queue automatically:

```bat
python manage.py run_print_simulator
python manage.py run_print_simulator --fail-rate 0.3
```

(PowerShell users: activate with `.\venv\Scripts\Activate.ps1` and copy with `Copy-Item`.)

### After pulling new changes

```bat
git status
git pull --ff-only
pip install -r requirements.txt
python manage.py migrate
python manage.py test
```

`git status` must show no local changes before pulling. Do **not** run `makemigrations` during
normal setup: migrations are part of the repository.

---

## 2. Demonstration walkthrough

1. Register a user (or log in) and choose **New Request**.
2. Upload a PDF (max 5 MB, not password-protected). The page count is read from the file; choose copies, colour, paper and duplex.
3. On the payment page press **Pay**. You are sent to the Chapify Pay test checkout.
4. Choose **Approve payment** (or **Decline** to see the retry path).
5. Back in Chapify, the request is *Payment confirmed* and the print job is *Queued*.
6. Log in as the administrator, open **Admin Dashboard** and press **Process next print job**
   (tick *Simulate printer failure* to demonstrate a failed job), or run `run_print_simulator`.
7. The user's request becomes *Completed* (or *Failed*); the uploaded file has been deleted.
8. The audit log (dashboard, report page, Django admin) shows every step.

## 3. Request lifecycle

| From | To | Trigger |
|---|---|---|
| AWAITING_PAYMENT | PAYMENT_CONFIRMED | gateway notification APPROVED |
| AWAITING_PAYMENT | PAYMENT_REJECTED | gateway notification DECLINED |
| PAYMENT_REJECTED | AWAITING_PAYMENT | user pays again |
| AWAITING_PAYMENT / PAYMENT_REJECTED | CANCELLED | user cancels, or not paid within the retention period |
| PAYMENT_CONFIRMED | COMPLETED | print job completed |
| PAYMENT_CONFIRMED | FAILED | print job failed |
| FAILED | PAYMENT_CONFIRMED | administrator retries the job |

Any other change is refused (`printing/services.py`, `ALLOWED_TRANSITIONS`).

Print jobs: `QUEUED -> IN_PROGRESS -> COMPLETED | FAILED` (an administrator can re-queue a failed job).
The uploaded file is deleted when the request is `COMPLETED` or `CANCELLED`; a `FAILED` request keeps
it for the retention period so the job can be retried.

Price (thesis §4.5): `pages (counted from the PDF) x copies x 0.10 EUR x colour (1.0/2.0) x paper (A4 1.0 / A3 1.8) x duplex (1.0/0.9)`,
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

## 5. Roles and administration

- **User**: own requests only (other users' requests return HTTP 404).
- **Administrator**: `Profile.role = ADMIN`. Accounts created with `createsuperuser` get this role
  automatically; others are promoted on the **Users** page. Used for the admin pages and the
  `/api/admin/*` endpoints. (The Django admin site itself also needs Django's *staff status*.)

Administrator pages (links in the top navigation):

| Page | Purpose |
|---|---|
| Admin Dashboard | Statistics, print queue, *Process next print job*, *Retry* for failed jobs, recent audit log |
| Users | Search accounts, block/unblock, make admin/user (not your own account) |
| Transactions | All payment attempts with status, payment reference and gateway transaction |
| Printers | Add printers, set Available / Offline / Error (only Available printers receive jobs) |
| Administrative Report | Summary counts and totals |

A **blocked** account cannot log in, its open sessions end and its API tokens are deleted.
A **failed** print job keeps its file so it can be retried; after the retention period the file
is removed by `cleanup_documents`.

Audit log events include logins, failed logins (username and IP address, never the password),
logouts, registrations, account and printer changes, payments and every print job status change.

## 6. REST API

Authentication: session, or token (`Authorization: Token <token>`).

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/token/` | Get a token (`username`, `password`) |
| GET | `/api/my/requests/` | Own print requests (`?status=`, `?q=`) |
| GET | `/api/my/requests/<id>/` | One own request |
| GET | `/api/my/payments/` | Own payment attempts |
| GET | `/api/my/print-jobs/` | Own print jobs |
| POST | `/api/requests/create/` | Create a request (multipart: `file` (PDF), `copies`, `color_mode` BW/COLOR, `paper_format` A4/A3, `duplex_mode` ONE_SIDED/DOUBLE_SIDED). Pages are counted from the PDF. |
| POST | `/api/requests/<id>/payment/` | Start a payment; returns `checkout_url` for the payer |
| POST | `/api/requests/<id>/cancel/` | Cancel an unpaid request |
| POST | `/payments/callback/` | Gateway webhook (form field or JSON `notification`; no login, signature-verified) |
| GET | `/api/admin/summary/`, `requests/`, `transactions/`, `print-jobs/`, `printers/`, `audit-logs/` | Administrator only |

Command Prompt examples (`curl` is built into Windows; placeholders in `<...>`):

```bat
curl -X POST http://127.0.0.1:8000/api/auth/token/ -d "username=<user>" -d "password=<password>"
curl -H "Authorization: Token <token>" -F "file=@report.pdf" -F "copies=2" -F "color_mode=BW" -F "paper_format=A4" -F "duplex_mode=ONE_SIDED" http://127.0.0.1:8000/api/requests/create/
curl -H "Authorization: Token <token>" -X POST http://127.0.0.1:8000/api/requests/<id>/payment/
```

Open the returned `checkout_url` in a browser to approve or decline the payment.

## 7. Management commands

| Command | Purpose |
|---|---|
| `python manage.py run_print_simulator [--once] [--fail-rate 0.2] [--seconds-per-page 0.5]` | Simulated print server |
| `python manage.py cleanup_documents [--hours 24] [--dry-run]` | Retention policy: expire unpaid requests, delete abandoned uploads |

## 8. Tests

```bat
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
