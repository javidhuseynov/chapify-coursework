"""Load test for Chapify (Locust). Guide: docs/LOAD_TESTING.md

Two kinds of simulated students, each logged in as one of the
loadtest_NNN accounts (python manage.py create_loadtest_users):

- Browsing student (3 of 4 users): opens the home page and their request
  list, looks at a request, checks their payments.
- Printing student (1 of 4 users): uploads a PDF through the API, starts
  the payment (Chapify creates a checkout session at Chapify Pay), and pays
  with a test card on the gateway's page. The gateway then sends its signed
  webhook to Chapify, so every payment exercises all of:
  Chapify API -> Chapify Pay API -> card page -> webhook -> Chapify.

Run (from the project folder):
    locust -f loadtest/locustfile.py --host http://127.0.0.1:8000
"""

import io
import itertools
import os
import random
import re

from locust import HttpUser, between, events, task
from pypdf import PdfWriter

GATEWAY = os.environ.get("CHAPIFY_PAY_URL", "http://127.0.0.1:8001").rstrip("/")
PASSWORD = os.environ.get("LOADTEST_PASSWORD", "Load-test-pass-2026")
ACCOUNTS = int(os.environ.get("LOADTEST_ACCOUNTS", "50"))
_numbers = itertools.cycle(range(1, ACCOUNTS + 1))
CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


def make_pdf(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


PDFS = {pages: make_pdf(pages) for pages in (1, 3, 10)}


class Student(HttpUser):
    abstract = True

    def on_start(self):
        self.username = f"loadtest_{next(_numbers):03d}"
        self.token = None
        self.log_in_to_api()
        self.log_in_to_website()

    def log_in_to_api(self):
        with self.client.post(
            "/api/auth/token/",
            data={"username": self.username, "password": PASSWORD, "name": "Load test"},
            name="API: log in (token)",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                self.token = response.json()["token"]
            else:
                response.failure(f"login failed: {response.status_code} {response.text[:120]}")

    def log_in_to_website(self):
        page = self.client.get("/login/", name="Web: login page")
        match = CSRF.search(page.text)
        if match:
            self.client.post(
                "/login/",
                data={"username": self.username, "password": PASSWORD, "csrfmiddlewaretoken": match.group(1)},
                headers={"Referer": self.host + "/login/"},
                name="Web: log in",
                allow_redirects=False,
            )

    @property
    def auth(self):
        return {"Authorization": f"Token {self.token}"}


class BrowsingStudent(Student):
    weight = 3
    wait_time = between(2, 6)

    @task(3)
    def home(self):
        self.client.get("/", name="Web: home")

    @task(2)
    def history(self):
        self.client.get("/history/", name="Web: my requests")

    @task(3)
    def api_requests(self):
        if not self.token:
            return
        response = self.client.get("/api/my/requests/", headers=self.auth, name="API: my requests")
        if response.status_code == 200 and response.json():
            request_id = random.choice(response.json())["id"]
            self.client.get(f"/api/my/requests/{request_id}/", headers=self.auth, name="API: one request")

    @task(1)
    def api_payments(self):
        if self.token:
            self.client.get("/api/my/payments/", headers=self.auth, name="API: my payments")


class PrintingStudent(Student):
    weight = 1
    wait_time = between(5, 15)

    @task
    def upload_and_pay(self):
        if not self.token:
            return
        pages = random.choice(list(PDFS))

        # 1. Upload and create the request (server counts pages and prices it).
        with self.client.post(
            "/api/requests/create/",
            headers=self.auth,
            data={"copies": "1", "color_mode": random.choice(["BW", "COLOR"]), "paper_format": "A4", "duplex_mode": "ONE_SIDED"},
            files={"file": (f"loadtest-{pages}p.pdf", PDFS[pages], "application/pdf")},
            name="API: upload + create request",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"{response.status_code} {response.text[:120]}")
                return
            request_id = response.json()["print_request"]["id"]

        # 2. Start the payment: Chapify creates a checkout session at the gateway.
        with self.client.post(
            f"/api/requests/{request_id}/payment/",
            headers=self.auth,
            name="API: start payment (Chapify -> gateway)",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"{response.status_code} {response.text[:120]}")
                return
            checkout_url = response.json()["checkout_url"]

        # 3. Pay on the gateway's card page (9 in 10 succeed, 1 is declined).
        page = self.client.get(checkout_url, name="Gateway: card page")
        match = CSRF.search(page.text)
        if not match:
            return
        card = "4242424242424242" if random.random() < 0.9 else "4000000000009995"
        with self.client.post(
            checkout_url,
            data={"csrfmiddlewaretoken": match.group(1), "name": "Load Test", "number": card, "expiry": "12/30", "cvc": "123"},
            headers={"Referer": checkout_url},
            name="Gateway: pay (incl. webhook to Chapify)",
            allow_redirects=False,
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 302):
                response.failure(f"{response.status_code}")


@events.test_start.add_listener
def describe(environment, **kwargs):
    print(f"Chapify load test: target {environment.host}, gateway {GATEWAY}, {ACCOUNTS} accounts.")
