"""Take screenshots of the running app (used by .github/workflows/screenshots.yml).

Assumes: server on http://127.0.0.1:8000, `seed_demo --password Demo-pass-2026` run on an empty database.
"""

import io
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

BASE = "http://127.0.0.1:8000"
GATEWAY = "http://127.0.0.1:8001"
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


def pay_with_card(page, number):
    """Fill in the card form on the Chapify Pay checkout page and pay."""
    assert page.url.startswith(GATEWAY), page.url
    page.fill("#id_name", "Demo Student")
    page.fill("#id_number", number)
    page.fill("#id_expiry", "12/30")
    page.fill("#id_cvc", "123")
    page.click("button.pay-button")
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
    pay_with_card(page, "4242 4242 4242 4242")
    shoot(page, f"{prefix}14-after-payment")
    if prefix == "desktop-":
        # Request 5 (seed data) is waiting for payment: pay it with a card that is declined.
        page.goto(BASE + "/payment/5/")
        page.click("main form button[type=submit]")
        page.wait_for_load_state("networkidle")
        pay_with_card(page, "4000 0000 0000 9995")
        shoot(page, f"{prefix}16-gateway-declined")
        page.click("a.pay-button")
        page.wait_for_load_state("networkidle")
        shoot(page, f"{prefix}17-after-decline")
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
    page.goto(BASE + "/api/docs/")
    page.wait_for_selector(".swagger-ui .info", timeout=15000)
    shoot(page, f"{prefix}28-api-docs")

    if errors:
        print("CONSOLE ERRORS:", *errors, sep="\n  ")
    context.close()
    return [e for e in errors if "Content Security Policy" in e]


def station_setup(browser):
    """Connect Library Printer 1 to a print station through the admin UI; save the key."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login(page, "demo_admin")
    page.goto(BASE + "/admin-printers/")
    row = page.locator("tr", has_text="Library Printer 1")
    row.get_by_role("button", name="Connect a print station").click()
    page.wait_for_load_state("networkidle")
    shoot(page, "desktop-30-station-key")
    key = page.locator("code.secret").inner_text().strip()
    Path("station.key").write_text(key)
    context.close()


def station_result(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login(page, "demo_admin")
    shoot(page, "desktop-33-printers-with-station", "/admin-printers/")
    shoot(page, "desktop-34-overview-with-station", "/admin-dashboard/")
    shoot(page, "desktop-35-audit-with-station", "/admin-audit/?status=PRINT_STATION")
    shoot(page, "desktop-36-admin-payments", "/admin-transactions/")

    # The gateway's own merchant dashboard (separate application and login).
    page.goto(GATEWAY + "/dashboard/login/")
    page.fill("#id_username", "gateway_admin")
    page.fill("#id_password", PASSWORD)
    page.press("#id_password", "Enter")
    page.wait_for_load_state("networkidle")
    page.goto(GATEWAY + "/dashboard/checkout/checkoutsession/")
    shoot(page, "desktop-40-gateway-sessions")
    page.goto(GATEWAY + "/dashboard/checkout/webhookevent/")
    shoot(page, "desktop-41-gateway-webhooks")
    page.goto(GATEWAY + "/")
    shoot(page, "desktop-42-gateway-home")
    context.close()


MODE = sys.argv[2] if len(sys.argv) > 2 else "pages"

with sync_playwright() as p:
    browser = p.chromium.launch()
    violations = []
    if MODE == "pages":
        violations = run(browser, "desktop-", {"width": 1440, "height": 900})
        violations += run(browser, "mobile-", {"width": 390, "height": 844})
    elif MODE == "station-setup":
        station_setup(browser)
    elif MODE == "station-result":
        station_result(browser)
    browser.close()

if violations:
    sys.exit("Content-Security-Policy violations found (see console errors above).")
