"""Take screenshots of the running app (used by .github/workflows/screenshots.yml).

Assumes: server on http://127.0.0.1:8000, `seed_demo --password Demo-pass-2026` run on an empty database.
"""

import io
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

BASE = "http://127.0.0.1:8000"
PASSWORD = "Demo-pass-2026"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def pdf(path, pages=6):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    Path(path).write_bytes(buffer.getvalue())


def shoot(page, name, url=None):
    if url:
        page.goto(BASE + url)
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print("saved", name)


def login(page, username):
    page.goto(BASE + "/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", PASSWORD)
    page.press("#id_password", "Enter")
    page.wait_for_load_state("networkidle")


def run(browser, prefix, viewport):
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    shoot(page, f"{prefix}01-login", "/login/")
    shoot(page, f"{prefix}02-register", "/register/")

    login(page, "demo_student")
    shoot(page, f"{prefix}03-user-home")
    shoot(page, f"{prefix}04-history", "/history/")
    shoot(page, f"{prefix}05-request-completed", "/status/1/")
    shoot(page, f"{prefix}06-request-queued", "/status/3/")
    shoot(page, f"{prefix}07-help", "/help/")
    shoot(page, f"{prefix}08-account", "/account/")

    page.goto(BASE + "/upload/")
    shoot(page, f"{prefix}09-upload")
    pdf("/tmp/thesis_chapter.pdf")
    page.set_input_files("input[type=file]", "/tmp/thesis_chapter.pdf")
    shoot(page, f"{prefix}10-upload-selected")
    page.click("main button[type=submit]")
    page.wait_for_load_state("networkidle")
    if prefix == "desktop-":
        page.check("input[name=color_mode][value=COLOR]", force=True)
    shoot(page, f"{prefix}11-settings")
    page.click("main button[type=submit]")
    page.wait_for_load_state("networkidle")
    shoot(page, f"{prefix}12-payment")
    page.click("main form button[type=submit]")
    page.wait_for_load_state("networkidle")
    shoot(page, f"{prefix}13-gateway")
    page.click("button[value=approve]")
    page.wait_for_load_state("networkidle")
    shoot(page, f"{prefix}14-after-payment")
    shoot(page, f"{prefix}15-404", "/no-such-page/")
    context.clear_cookies()

    login(page, "demo_admin")
    shoot(page, f"{prefix}20-admin-overview")
    shoot(page, f"{prefix}21-admin-requests", "/admin-requests/")
    shoot(page, f"{prefix}22-admin-users", "/admin-users/")
    shoot(page, f"{prefix}23-admin-payments", "/admin-transactions/")
    shoot(page, f"{prefix}24-admin-printers", "/admin-printers/")
    shoot(page, f"{prefix}25-admin-audit", "/admin-audit/")
    shoot(page, f"{prefix}26-admin-reports", "/admin-report/")
    shoot(page, f"{prefix}27-django-admin", "/admin/printing/printrequest/")

    if errors:
        print("CONSOLE ERRORS:", *errors, sep="\n  ")
    context.close()


with sync_playwright() as p:
    browser = p.chromium.launch()
    run(browser, "desktop-", {"width": 1440, "height": 900})
    run(browser, "mobile-", {"width": 390, "height": 844})
    browser.close()
