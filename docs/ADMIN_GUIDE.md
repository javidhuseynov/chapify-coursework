# Chapify administrator guide

For staff who supervise the printing service. Installation and start-up are described in the
README (developer guide); this guide covers daily administration.

## 1. Becoming an administrator

- The account created with `python manage.py createsuperuser` is an administrator.
- An administrator can make other accounts administrators on the **Users** page.
- Administrator links appear in the top navigation: **Admin Dashboard**, **Users**,
  **Transactions**, **Printers**. Staff accounts also see **Django Admin** (`/admin/`), the
  low-level database tool.

## 2. Admin Dashboard

| Section | Use |
|---|---|
| Counters | Requests, confirmed / rejected payments, completed / failed jobs |
| Print Queue | Jobs that are queued or printing, and which printer they use |
| Process next print job | Runs one step of the simulated print server (tick *Simulate printer failure* to demonstrate a failure) |
| Recently failed jobs | Failure reason and a **Retry** button |
| Printers | Current status of each printer |
| Recent Print Requests | Search by request number, username or file name; filter by status |
| Recent Audit Logs | The latest security and workflow events |

**Administrative Report** (link on the dashboard) summarises requests, payments and jobs by
status and the total confirmed amount.

### Processing the queue

Either press **Process next print job** for each job, or start the simulated print server in a
second command window (with the virtual environment activated):

```bat
python manage.py run_print_simulator
python manage.py run_print_simulator --fail-rate 0.2
```

It processes jobs continuously until Ctrl+C. `--fail-rate 0.2` makes 20 % of jobs fail.

### Retrying a failed job

A failed job keeps its document for 24 hours. In **Recently failed jobs** press **Retry**: the job
goes back to the queue and the request to *Payment confirmed*. Retry is refused when the file has
already been deleted. Payments are not refunded automatically.

## 3. Users

- Search by username or email; filter by account status.
- **Block**: the user can no longer log in, any open session ends immediately and their API token
  is deleted. Their existing requests stay in the system.
- **Unblock**: access is restored.
- **Make admin / Make user**: changes the role.
- You cannot block or change the role of your own account (prevents locking yourself out).
- Every change is written to the audit log.

## 4. Transactions

All payment attempts: date, user, request, amount, status (Initiated, Confirmed, Rejected,
Cancelled), Chapify's payment reference and the gateway's transaction id. Filter by status and
search by username, request number, payment reference or gateway transaction id. The total of
confirmed payments in the current selection is shown at the top. No card data exists in Chapify.

## 5. Printers

- **Add printer**: name and location.
- **Change status**: Available, Offline or Error. Only *Available* printers receive jobs; jobs
  wait in the queue while no printer is available. *Busy* is set automatically while a printer is
  printing and cannot be changed by hand.

## 6. Audit log

Recorded events include: registration, login, failed login (username and IP address, never the
password), refused logins after too many attempts, logout, document upload and validation,
request creation, update and cancellation, payment initiation, confirmation and rejection,
refused (forged, expired or mismatching) payment notifications, print job creation and status
changes, file deletion, account changes and printer changes.

View it on the dashboard, the report page, or in full in **Django Admin → Audit logs** (filter
by event type and date, search the description).

## 7. Routine maintenance

Run the retention policy regularly (for example daily):

```bat
python manage.py cleanup_documents
python manage.py cleanup_documents --dry-run
```

It cancels requests not paid within 24 hours, deletes uploads that never became a request, and
deletes files of failed jobs older than 24 hours. The period is set by
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
| `CHAPIFY_SECRET_KEY`, `CHAPIFY_PAYMENT_GATEWAY_SECRET` | Long random values; with `CHAPIFY_DEBUG=False` Chapify refuses to start with the development defaults |
| `CHAPIFY_DEBUG=False` | Never show debug pages on a shared server |
| `CHAPIFY_ALLOWED_HOSTS` | The server's host name |
| `CHAPIFY_HTTPS=True` | HTTPS-only cookies, redirect to HTTPS, HSTS (only behind a working TLS certificate) |
| `CHAPIFY_LOGIN_FAILURE_LIMIT`, `CHAPIFY_LOGIN_LOCKOUT_SECONDS` | Login lockout (default 5 attempts, 15 minutes) |

Check a configuration with `python manage.py check --deploy`.
