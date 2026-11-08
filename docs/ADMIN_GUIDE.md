# Chapify administrator guide

For staff who supervise the printing service. Installation and start-up are described in the
README (developer guide); this guide covers daily administration.

## 1. Becoming an administrator

- The account created with `python manage.py createsuperuser` is an administrator.
- An administrator can make other accounts administrators on the **Users** page.
- After logging in, an administrator lands on **Overview** instead of the student home page. The
  side menu has **Operations** (Overview, Requests, Printers) and **Administration** (Users,
  Payments, Audit log, Reports). Staff accounts also see **Database admin** (`/admin/`), the
  low-level Django tool. Student pages such as *Print a document* are not shown to
  administrators.
- Hiding links is only convenience: every administrator page and `/api/admin/*` endpoint checks
  the role on the server and returns *403* to students.

## 2. Overview

| Section | Use |
|---|---|
| Counters | Waiting to print, printed today, failed jobs, paid today, open requests |
| Print queue | Jobs that are queued or printing, and which printer they use |
| Print next job | Runs one step of the simulated print server (tick *Simulate a printer fault* to demonstrate a failure) |
| Failed jobs | Failure reason and a **Print again** button |
| Printers | Current status of each printer |
| Recent activity | The latest security and workflow events (full list: **Audit log**) |

**Requests** lists every request from every user (search by request number, username or file
name; filter by status). **Reports** summarises requests, payments and jobs by status, printed
pages and the total confirmed amount.

### Processing the queue

Printers connected to a **print station** (section 5) take their jobs by themselves. For printers
without a station, press **Print next job** for each job, or start the built-in simulator in a
second command window (with the virtual environment activated):

```bat
python manage.py run_print_simulator
python manage.py run_print_simulator --fail-rate 0.2
```

It processes jobs continuously until Ctrl+C. `--fail-rate 0.2` makes 20 % of jobs fail.

### Printing a failed job again

A failed job keeps its document for 24 hours. In **Failed jobs** press **Print again**: the job
goes back to the queue and the request to *Payment confirmed*. This is refused when the file has
already been deleted. Payments are not refunded automatically.

## 3. Users

- Search by username or email; filter by account status.
- **Block**: the user can no longer log in, any open session ends immediately and all their API
  tokens (signed-in apps) are revoked. Their existing requests stay in the system.
- **Unblock**: access is restored.
- **Make administrator / Make student**: changes the role.
- You cannot block or change the role of your own account (prevents locking yourself out).
- Every change is written to the audit log.

## 4. Payments

All payment attempts: date, user, request, amount, status (Initiated, Confirmed, Rejected,
Cancelled), Chapify's payment reference and the gateway's transaction id. Filter by status and
search by username, request number, payment reference or gateway transaction id. The total of
confirmed payments in the current selection is shown at the top. No card data exists in Chapify.

The payment provider has its own **merchant dashboard** (Chapify Pay, http://127.0.0.1:8001/dashboard/,
a separate login created with `python manage.py createsuperuser` in the `gateway_service` folder).
It lists checkout sessions, payments (card brand and last four digits only) and webhook deliveries;
a webhook that Chapify did not accept (for example because Chapify was stopped) is retried
automatically, or can be sent again with the action *Send the selected webhooks again*.

## 5. Printers and print stations

- **Add printer**: name and location.
- **Connect a print station**: generates the printer's **station key** and shows it once, with the
  command to start the station. The printer stays *Offline* until the station connects. The key
  works only for the printer API and only for this printer's jobs; Chapify stores only its
  fingerprint (hash). **New station key** replaces it (the old one stops working); **Disconnect**
  removes it and returns the printer to the built-in simulator.
- The **Print station** column shows *Connected, last seen …*, the reported paper and toner, the
  key's first characters and the station version, or *Not responding since …*.
- A station reports its own status: switched off → *Offline*; jam, no paper or no toner →
  *Error*. These printers' status cannot be set by hand.
- If a station stops sending heartbeats for 60 seconds, Chapify marks the printer *Offline* and
  fails the job it was printing (reason *Print station stopped responding*); use **Print again**.
- Printers without a station: **Change status** to Available, Offline or Error by hand.
- Only *Available* printers receive jobs; jobs wait in the queue while no printer is available.
  *Busy* is set automatically while a printer is printing.

Command-line alternative: `python manage.py printer_station_key "Library Printer 1"`.
Starting and operating a station: [print_station/README.md](../print_station/README.md).

## 6. Audit log

Recorded events include: registration, login, failed login (username and IP address, never the
password), refused logins after too many attempts, logout, document upload and validation,
request creation, update and cancellation, payment initiation, confirmation and rejection,
refused (forged, expired or mismatching) payment notifications, print job creation and status
changes, file deletion, account changes and printer changes.

The latest events are on **Overview**; the full log, filterable by event type and searchable,
is on **Audit log** (and in **Database admin → Audit logs**).

## 7. Routine maintenance

Run the retention policy regularly (for example daily):

```bat
python manage.py cleanup_documents
python manage.py cleanup_documents --dry-run
```

It cancels requests not paid within 24 hours, deletes uploads that never became a request,
deletes files of failed jobs older than 24 hours, and removes API tokens that expired or were
revoked more than 30 days ago. The period is set by
`CHAPIFY_DOCUMENT_RETENTION_HOURS` in `.env`.

## 8. Demonstration data

To fill an empty database before a demonstration:

```bat
python manage.py seed_demo --password <choose-a-password>
```

It creates `demo_admin`, `demo_student`, `demo_student2`, two printers and requests in every
state (completed, failed, queued, payment declined, awaiting payment, cancelled).

## 9. Security settings (for a hosted deployment)

In `.env`:

| Setting | Purpose |
|---|---|
| `CHAPIFY_SECRET_KEY`, `CHAPIFY_PAY_API_KEY`, `CHAPIFY_PAY_WEBHOOK_SECRET` | Long random values; with `CHAPIFY_DEBUG=False` Chapify refuses to start with the development defaults |
| `CHAPIFY_API_TOKEN_TTL_HOURS` | Lifetime of API tokens (default 168 = 7 days) |
| `CHAPIFY_PRINT_STATION_TIMEOUT_SECONDS` | Silence after which a print station counts as stopped (default 60) |
| `CHAPIFY_PAYMENT_GATEWAY=stripe` + `CHAPIFY_STRIPE_SECRET_KEY`, `CHAPIFY_STRIPE_WEBHOOK_SECRET` | Use Stripe in test mode instead of Chapify Pay (only `sk_test_` keys are accepted) |
| `CHAPIFY_DEBUG=False` | Never show debug pages on a shared server |
| `CHAPIFY_ALLOWED_HOSTS` | The server's host name |
| `CHAPIFY_HTTPS=True` | HTTPS-only cookies, redirect to HTTPS, HSTS (only behind a working TLS certificate) |
| `CHAPIFY_LOGIN_FAILURE_LIMIT`, `CHAPIFY_LOGIN_LOCKOUT_SECONDS` | Login lockout (default 5 attempts, 15 minutes) |

Check a configuration with `python manage.py check --deploy`.
