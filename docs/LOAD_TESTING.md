# Load testing Chapify

The load test simulates many students using Chapify at the same time and measures response
times and errors. It uses [Locust](https://locust.io) and drives all three applications:

- **Browsing students** (3 of 4): home page, request list, one request, payments.
- **Printing students** (1 of 4): upload a PDF through the API → start the payment (Chapify
  creates a checkout session at Chapify Pay) → pay on the gateway's card page (9 of 10 succeed,
  1 is declined) → the gateway sends its signed webhook to Chapify.

The scenario is in `loadtest/locustfile.py`. It runs against **waitress**, a production-grade
server (`serve.py`), because Django's `runserver` is for development only and would distort the
numbers.

## 1. Once: install and create test accounts (Command Prompt, project folder)

```bat
cd "C:\Users\Asus ROG\Desktop\chapify_project"
venv\Scripts\activate
pip install -r requirements-loadtest.txt
copy db.sqlite3 db-before-loadtest.sqlite3
python manage.py create_loadtest_users --count 50
```

The `copy` line keeps a backup of your database; the test creates many requests and payments.
The accounts are `loadtest_001` … `loadtest_050` with the password `Load-test-pass-2026`.

## 2. Start the servers (two windows)

Close any `runserver` / `start_demo.bat` windows first (they use the same ports).

**Window 1 – Chapify.** The two `set` lines raise the API rate limits *in this window only*,
because all simulated users come from one address (127.0.0.1) and would otherwise be throttled:

```bat
cd "C:\Users\Asus ROG\Desktop\chapify_project"
venv\Scripts\activate
set CHAPIFY_THROTTLE_ANON=100000/minute
set CHAPIFY_THROTTLE_USER=100000/minute
python serve.py
```

**Window 2 – Chapify Pay:**

```bat
cd "C:\Users\Asus ROG\Desktop\chapify_project\gateway_service"
..\venv\Scripts\activate
python serve.py
```

(Pages look unstyled under `serve.py`; that is expected, it does not serve CSS files. It does not
matter for the test.)

## 3. Run the test (third window)

**With the Locust web page** (good for watching live charts and taking screenshots):

```bat
cd "C:\Users\Asus ROG\Desktop\chapify_project"
venv\Scripts\activate
locust -f loadtest/locustfile.py --host http://127.0.0.1:8000
```

Open http://localhost:8089, enter *Number of users* (e.g. 50) and *Ramp up* (e.g. 5 per second),
press **Start**. The *Charts* tab shows requests per second, response times and failures; stop
after a few minutes. *Download Data* saves the results.

**Without the web page, saving results to files:**

```bat
locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless -u 50 -r 5 -t 3m --csv results-50
python loadtest/summary.py results-50_stats.csv
```

`summary.py` prints a Markdown table you can paste into the thesis.

## 4. A test plan for the thesis

Run the headless command several times, increasing the number of users, 3 minutes each:

| Run | Users (`-u`) | Ramp (`-r`) | Files (`--csv`) |
|---|---:|---:|---|
| 1 | 10 | 2 | `results-10` |
| 2 | 50 | 5 | `results-50` |
| 3 | 100 | 10 | `results-100` |
| 4 | 200 | 10 | `results-200` |

For each run, write down from the *All requests* row: requests per second, median and 95th
percentile response time, and failures. Note your computer (CPU, RAM) since results depend on it.
The point where the 95th percentile rises sharply or failures appear is the capacity of this
set-up.

**What to expect and how to explain it**

- *Log in* takes about 0.5 s on purpose: passwords are stored with PBKDF2 using over a million
  iterations, which makes stolen password hashes slow to crack. It happens once per session.
- At high load, failures with *database is locked* come from **SQLite**, which allows one write at
  a time. This is the known limit of the development database; the remedy is PostgreSQL (a
  settings change) and several server processes with a shared cache.
- **Connection limit of the server.** Each simulated user keeps one connection open. waitress
  accepts only 100 open connections by default, so in the first 100/200-user runs (12 November
  2026) only 98 users ever logged in. The others waited in a queue for the whole run, and the
  gateway's webhook to Chapify had to queue too. As a result, payment start-ups timed out after
  10 s (503 "payment service cannot be reached") and card pages took 15 s or more. Both
  `serve.py` files now allow 1,000 connections (`--connection-limit`). If the limit is still
  reached, the server window shows a waitress warning that it is "no longer accepting new
  connections".
- Each payment involves three server-to-server calls (create session, webhook, status), so it is
  the slowest flow after login.

Example from the CI run (GitHub Actions Linux machine, 30 users, 60 s): 596 requests, **0
failures**, median 9 ms, 95th percentile 510 ms (log-ins), 49 print requests uploaded, 44 payments
confirmed and 5 declined through the gateway.

## 5. Afterwards

```bat
python manage.py create_loadtest_users --delete
```

deletes the test accounts and everything they created. Or restore the backup:
`copy /Y db-before-loadtest.sqlite3 db.sqlite3` (with the servers stopped). Closing window 1 also
ends the raised rate limits; nothing was changed in `.env`.

The **Load test** workflow on GitHub (Actions → Load test → Run workflow) runs the same scenario
with a chosen number of users and prints the results table in its log.
