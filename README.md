# Chapify

![Tests](https://github.com/javidhuseynov/chapify-coursework/actions/workflows/tests.yml/badge.svg)

Self-service printing information system with integrated micro-payment functionality
(bachelor's thesis project, Vilnius University Kaunas Faculty).

A user uploads a document, chooses print settings, sees the calculated price, pays through a
payment gateway and follows the print job until it is printed. Administrators monitor the
print queue, payments, printers and the audit log.

The system consists of **three separate applications** that talk to each other only over HTTP:

```
                      ┌───────────────────────────── browser ─────────────────────────────┐
                      │  students and administrators                payers (card form)     │
                      └──────────────┬──────────────────────────────────────┬─────────────┘
                                     │                                      │
   ┌─────────────────────────────────▼──────────┐   checkout API    ┌───────▼────────────────────┐
   │ Chapify  (this folder, port 8000)          │ ────────────────► │ Chapify Pay (port 8001)    │
   │ web app + REST API + OpenAPI docs          │ ◄──────────────── │ gateway_service/           │
   │ requests, prices, payments, queue, audit   │  signed webhooks  │ test payment gateway       │
   └─────────────────────────────────▲──────────┘                   └────────────────────────────┘
                                     │ printer API (station key)
   ┌─────────────────────────────────┴──────────┐
   │ Print station  (print_station/)            │   one per printer; window or headless
   │ takes jobs, downloads PDF, "prints", reports│
   └────────────────────────────────────────────┘
```

- **Chapify** (`chapify/`, `printing/`): Python 3.12+, Django 6.1, Django REST Framework, SQLite;
  own CSS/JS (no CDN); OpenAPI 3 schema with Swagger UI at `/api/docs/`.
- **Chapify Pay** (`gateway_service/`): separate Django project with its own database, playing an
  external payment provider: checkout sessions, hosted card page (test cards only), signed
  webhooks with retries, merchant dashboard. A **Stripe test-mode** adapter can be used instead.
  See [gateway_service/README.md](gateway_service/README.md).
- **Print station** (`print_station/`): standard-library program with a window, one per printer,
  authenticated with a printer key. See [print_station/README.md](print_station/README.md).
  Printers without a station are driven by Chapify's built-in simulator.

**Documentation:** [User guide](docs/USER_GUIDE.md) · [Administrator guide](docs/ADMIN_GUIDE.md) ·
[Requirement-to-test traceability](docs/TRACEABILITY.md) · [Security checklist](docs/SECURITY_CHECKLIST.md). This README is the developer guide.

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
`python -c "import secrets; print(secrets.token_urlsafe(50))"` (keep the `sk_test_` and `whsec_`
prefixes). `.env` is never committed. The gateway reads the same file, so both sides agree on the
API key and webhook secret. The account created with `createsuperuser` becomes a Chapify administrator.

### Every session: start everything

```bat
cd chapify-coursework
start_demo.bat
```

`start_demo.bat` applies migrations for both applications and opens a window for each server:
Chapify on http://127.0.0.1:8000/ and Chapify Pay on http://127.0.0.1:8001/. To also start a
print station, connect a printer first (**Printers → Connect a print station**), then in a new
Command Prompt window:

```bat
cd chapify-coursework
venv\Scripts\activate.bat
set CHAPIFY_STATION_KEY=<the key shown in Chapify>
python -m print_station
```

The same by hand, one window each (activate the venv in every window):

```bat
python manage.py runserver
cd gateway_service && python manage.py runserver 127.0.0.1:8001
python -m print_station --server http://127.0.0.1:8000
```

Printers without a print station are processed by the built-in simulator: **Print next job** on
the administrator Overview, or `python manage.py run_print_simulator` in another window.

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

Optional: fill the database first with `python manage.py seed_demo --password <choose-a-password>`
(demo accounts `demo_admin`, `demo_student`, `demo_student2` and requests in every state).

1. As the administrator, open **Printers**, press **Connect a print station** next to *Library
   Printer 1* and start the print station with the key (see above). Its window shows *Ready*.
2. Register a user (or log in) and choose **Print a document**.
3. Upload a PDF (max 5 MB, not password-protected). The page count is read from the file; choose
   copies, color, paper size and sides; the price estimate updates as you choose.
4. On the payment page press **Pay**. The browser goes to the Chapify Pay checkout (port 8001).
5. Pay with test card `4242 4242 4242 4242` (any name, future date, 3 digits), or with
   `4000 0000 0000 9995` to see a declined payment and the retry path.
6. Back in Chapify, the request is *Payment confirmed* and the print job *Queued*.
7. The print station takes the job within a few seconds: its window shows the progress, paper and
   toner. Tick *Jam the next job* to demonstrate a failure, then *Clear jam* and **Print again**.
8. The user's request becomes *Completed* (or *Failed*); the uploaded file has been deleted.
9. **Audit log** in Chapify shows every step; the gateway's dashboard
   (http://127.0.0.1:8001/dashboard/) shows the payment and the webhook delivery.

## 3. Request lifecycle

| From | To | Trigger |
|---|---|---|
| AWAITING_PAYMENT | PAYMENT_CONFIRMED | gateway reports the payment as paid |
| AWAITING_PAYMENT | PAYMENT_REJECTED | gateway reports the card as declined |
| PAYMENT_REJECTED | AWAITING_PAYMENT | user pays again |
| AWAITING_PAYMENT / PAYMENT_REJECTED | CANCELLED | user cancels, or not paid within the retention period |
| PAYMENT_CONFIRMED | COMPLETED | print job completed |
| PAYMENT_CONFIRMED | FAILED | print job failed |
| FAILED | PAYMENT_CONFIRMED | administrator retries the job |

Any other change is refused (`printing/services.py`, `ALLOWED_TRANSITIONS`).

Print jobs: `QUEUED -> IN_PROGRESS -> COMPLETED | FAILED` (an administrator can re-queue a failed job).
The uploaded file is deleted when the request is `COMPLETED` or `CANCELLED`; a `FAILED` request keeps
it for the retention period so the job can be retried.

Price (thesis §4.5): `pages (counted from the PDF) x copies x 0.10 EUR x color (1.0/2.0) x paper (A4 1.0 / A3 1.8) x duplex (1.0/0.9)`,
calculated with exact decimals and rounded half-up to cents (`printing/pricing.py`).

## 4. Payment security design

Details and a sequence diagram: [gateway_service/README.md](gateway_service/README.md).

1. **Pay** creates a `PaymentTransaction` (`INITIATED`, unique UUID `reference`). Chapify then
   creates a **checkout session** at the gateway, server to server, authenticated with its secret
   API key, with the amount and currency taken from the database. The browser never carries the
   amount, so it cannot change it.
2. The payer enters a card on the **gateway's** page. Chapify never sees card data.
3. The gateway reports the result in a **signed webhook** to `/payments/webhook/`:
   header `Chapify-Pay-Signature: t=<time>,v1=<HMAC-SHA256(webhook secret, "<time>.<body>")>`.
   Chapify accepts it only if the signature is valid and at most 5 minutes old (replay protection).
4. When the payer returns, Chapify **asks the gateway's API** for the session result, so the
   payment is recorded even if the webhook is late. The return URL itself proves nothing.
5. A result is applied only if the reference exists and is still `INITIATED` and amount and
   currency match. Status changes are atomic conditional updates; a repeated webhook is a
   duplicate; a database constraint allows at most one confirmed payment per request.
6. Refused notifications are written to the audit log (`PAYMENT_NOTIFICATION_REFUSED`).

No endpoint lets a user confirm a payment. With `CHAPIFY_PAYMENT_GATEWAY=stripe` the same flow
uses Stripe Checkout in **test mode**: `CHAPIFY_STRIPE_SECRET_KEY` must be a `sk_test_` key (live
keys are refused at start-up and live-mode events are rejected) and `CHAPIFY_STRIPE_WEBHOOK_SECRET`
is the signing secret, for example from `stripe listen --forward-to 127.0.0.1:8000/payments/webhook/`.
The Stripe adapter is covered by tests with Stripe's documented formats; it has not yet been run
against a live Stripe test account.

Other protections: login lockout after 5 failed attempts per username + IP for 15 minutes (web
and API), sessions expire after 8 hours or at browser close, Chapify refuses to start with
`DEBUG` off and the development secrets, and `CHAPIFY_HTTPS=True` enables HTTPS-only cookies,
redirect and HSTS. CI checks that configuration with `check --deploy`. Every response carries a
strict Content-Security-Policy and Permissions-Policy; registration has bot protection (honeypot,
minimum fill time, per-IP limit); requests over 6 MB are refused before being read; CI scans
dependencies with `pip-audit` and Dependabot proposes updates weekly. Details and the matching
tests: [docs/TRACEABILITY.md](docs/TRACEABILITY.md).

## 5. Roles and administration

- **User**: own requests only (other users' requests return HTTP 404).
- **Administrator**: `Profile.role = ADMIN`. Accounts created with `createsuperuser` get this role
  automatically; others are promoted on the **Users** page. Used for the admin pages and the
  `/api/admin/*` endpoints. (The Django admin site itself also needs Django's *staff status*.)

After login the role decides the start page and menu: students land on **Home**, administrators
on **Overview**. Hiding links is convenience only; every admin view checks the role on the server.

Administrator pages (side menu):

| Page | Purpose |
|---|---|
| Overview | Counters, print queue, *Print next job*, *Print again* for failed jobs, printers, recent activity |
| Requests | All requests from all users, searchable and filterable |
| Printers | Add printers; connect a print station (key shown once), see its connection, paper and toner; set Available / Offline / Error for printers without a station |
| Users | Search accounts, block/unblock, make administrator/student (not your own account) |
| Payments | All payment attempts with status, payment reference and gateway transaction |
| Audit log | Every recorded event, filterable by type |
| Reports | Totals by status, printed pages and confirmed revenue |

A **blocked** account cannot log in, its open sessions end and its API tokens are revoked.
A **failed** print job keeps its file so it can be retried; after the retention period the file
is removed by `cleanup_documents`.

Audit log events include logins, failed logins (username and IP address, never the password),
logouts, registrations, account and printer changes, payments and every print job status change.

## 6. REST API

Interactive documentation (Swagger UI): **http://127.0.0.1:8000/api/docs/** (log in first; also linked
as *API documentation* in the administrator menu). The machine-readable OpenAPI 3 description is at
`/api/schema/` (`?format=json` for JSON). CI checks that the schema is valid and that every endpoint is
described.

Authentication: session (browser), or an API token: `Authorization: Token <token>` (`Bearer` also
accepted). Tokens **expire** after `CHAPIFY_API_TOKEN_TTL_HOURS` (default 7 days), are stored only as a
SHA-256 hash, and are revoked when the user logs the app out, changes their password, or is blocked.
Users see and revoke their signed-in apps on the **Account** page.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/token/` | Log in: `username`, `password`, optional `name` (e.g. `Chapify mobile`). Returns the token once, with `expires_at` |
| POST | `/api/auth/token/revoke/` | Log out: revoke the token used for this request |
| GET | `/api/auth/tokens/` | List own active tokens |
| DELETE | `/api/auth/tokens/<id>/` | Revoke one own token |
| GET | `/api/my/requests/` | Own print requests (`?status=`, `?q=`) |
| GET | `/api/my/requests/<id>/` | One own request |
| GET | `/api/my/payments/` | Own payment attempts |
| GET | `/api/my/print-jobs/` | Own print jobs |
| POST | `/api/requests/create/` | Create a request (multipart: `file` (PDF), `copies`, `color_mode` BW/COLOR, `paper_format` A4/A3, `duplex_mode` ONE_SIDED/DOUBLE_SIDED). Pages are counted from the PDF. |
| POST | `/api/requests/<id>/payment/` | Start a payment; returns `checkout_url` for the payer |
| POST | `/api/requests/<id>/cancel/` | Cancel an unpaid request |
| POST | `/payments/webhook/` | Gateway webhook (no login; verified by the `Chapify-Pay-Signature` or `Stripe-Signature` header) |
| GET | `/api/admin/summary/`, `requests/`, `transactions/`, `print-jobs/`, `printers/`, `audit-logs/` | Administrator only |
| POST/GET | `/api/printer/heartbeat/`, `jobs/next/`, `jobs/<id>/document/`, `jobs/<id>/complete/`, `jobs/<id>/fail/` | Print stations only (`Authorization: Printer <key>`), see [print_station/README.md](print_station/README.md) |

Command Prompt examples (`curl` is built into Windows; placeholders in `<...>`):

```bat
curl -X POST http://127.0.0.1:8000/api/auth/token/ -d "username=<user>" -d "password=<password>"
curl -H "Authorization: Token <token>" -F "file=@report.pdf" -F "copies=2" -F "color_mode=BW" -F "paper_format=A4" -F "duplex_mode=ONE_SIDED" http://127.0.0.1:8000/api/requests/create/
curl -H "Authorization: Token <token>" -X POST http://127.0.0.1:8000/api/requests/<id>/payment/
```

Open the returned `checkout_url` in a browser and pay with a test card (for example `4242 4242 4242 4242`). A mobile app would open the same page in the system browser.

## 7. Management commands

| Command | Purpose |
|---|---|
| `python manage.py run_print_simulator [--once] [--fail-rate 0.2] [--seconds-per-page 0.5]` | Built-in simulated print server (printers without a print station) |
| `python manage.py printer_station_key "<printer name>"` | Generate a print station key (same as *Connect a print station* on the Printers page) |
| `python manage.py cleanup_documents [--hours 24] [--dry-run]` | Retention policy: expire unpaid requests, delete abandoned uploads and old files of failed jobs |
| `python manage.py seed_demo [--password <pw>]` | Demonstration data: demo accounts, printers, requests in every state |

## 8. Tests

```bat
python manage.py test
```

The gateway has its own tests: `cd gateway_service` then `python manage.py test`.

Load testing (many simultaneous users across all three applications, with Locust): see
[docs/LOAD_TESTING.md](docs/LOAD_TESTING.md).

GitHub Actions runs on every push to `main` and every pull request, on Windows and Linux with
Python 3.12 and 3.13 (`.github/workflows/tests.yml`): `check`, `makemigrations --check`, the
Chapify and print station tests, OpenAPI schema validation, the gateway's tests, `pip-audit` and
`check --deploy`. A second workflow (`screenshots.yml`) starts all three applications, pays with
test cards in a real browser, connects a print station through the admin pages, runs its window
on a virtual display, fails on any Content-Security-Policy violation, and publishes screenshots to
the `ci-screenshots` branch.

Test modules: `printing/tests/` (pricing and webhook signatures, workflow rules, payments through
a fake gateway, Stripe adapter, API tokens and OpenAPI, print queue and retention, print stations
including the real station program against a live test server, access control, security headers),
`print_station/tests/` (simulated printer), `gateway_service/checkout/tests/` (gateway API,
card page, webhook signing and retries).

## 9. Project structure

```
chapify/              settings (env-driven), root URLs, .env loader
printing/             Chapify application
  models.py           data model
  pricing.py          price formula (Decimal)
  services.py         workflow rules: status transitions, payments, print jobs, retention
  payment_gateways.py gateway clients (Chapify Pay, Stripe test mode), webhook signature check
  payments.py         payment flow: checkout, return, webhook
  stations.py         print stations: keys, heartbeats, job hand-out, watchdog
  printer_api.py      printer API for print stations
  api_tokens.py       expiring, revocable API tokens; api_auth.py: token endpoints
  api_docs.py         OpenAPI schema and Swagger UI
  permissions.py      administrator rule (RBAC)
  views.py            web pages and REST API
  management/         run_print_simulator, cleanup_documents, seed_demo, printer_station_key
  tests/              automated tests
gateway_service/      Chapify Pay: separate Django project (test payment gateway, port 8001)
print_station/        print station program (one per printer)
start_demo.bat        starts Chapify and the gateway (and a print station if a key is set)
private_media/        uploaded documents (git-ignored, never served over HTTP)
```
