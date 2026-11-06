# Security checklist (20 common web-application controls)

Assessment of Chapify against a widely shared "20 things every app should have" checklist.
Status: **Present** (implemented before this review), **Added** (implemented in this review),
**N/A** (concept from a different architecture; the equivalent control is named),
**Manual** (a repository/hosting setting the owner must switch on).

| # | Control | Status | How Chapify does it | Evidence (test or file) |
|---|---|---|---|---|
| 1 | Hide API keys | Present | Secrets (`CHAPIFY_SECRET_KEY`, `CHAPIFY_PAYMENT_GATEWAY_SECRET`) come from `.env`, which is git-ignored; nothing secret is sent to the browser; with `DEBUG=False` the app refuses to start with the development defaults | `chapify/settings.py`, `.env.example` |
| 2 | Purge Git secrets | Present + Manual | The June 2026 commit `2680f27` contained a Django `SECRET_KEY`. It is no longer used (keys now come from `.env`), so it is **rotated**, not purged: rewriting published history would need a force-push and still could not recall copies already cloned. GitHub secret scanning + push protection should be enabled to stop future leaks | `git log -S django-insecure-`; repository settings |
| 3 | Use public DB key | N/A | A Supabase/Firebase idea (client talks to the database directly). In Chapify the browser never talks to the database; only the Django server does | architecture |
| 4 | Row-level security | N/A → equivalent present | Enforced in the application layer: every query for user data is filtered by the logged-in user; other users' records return 404 | `test_access_control.ObjectOwnershipTests` |
| 5 | Encrypt sensitive data | Present (partly), see note | Passwords hashed (PBKDF2); no card data ever reaches Chapify; payment messages signed (HMAC-SHA256); HTTPS mode for transport. Uploaded PDFs are not encrypted at rest - they are kept only until printed/cancelled (retention policy) | `docs/TRACEABILITY.md` NFR-10 |
| 6 | Enforce server-side auth | Present | `login_required`, `chapify_admin_required`, DRF `IsAuthenticated`/`IsChapifyAdmin` on every protected view | `test_access_control.*` |
| 7 | Lock record access | Present | Ownership filters (IDOR protection); admin rule from `Profile.role` | `test_access_control.ObjectOwnershipTests`, `AdministratorAccessTests` |
| 8 | Block field tampering | Present | Forms and serializers list allowed fields explicitly; page count read from the PDF; payment amount carried in a signed session; status changes only through `services.transition` | `test_documents.TrustedPricingTests`, `test_payments.GatewayCheckoutFlowTests.test_amount_in_checkout_session_cannot_be_changed` |
| 9 | Secure session cookies | Present | HttpOnly and SameSite=Lax (Django defaults); `Secure` with `CHAPIFY_HTTPS=True`; 8-hour sessions ending at browser close | `chapify/settings.py`, CI `check --deploy` |
| 10 | Hash passwords | Present | Django PBKDF2-SHA256 with per-user salt; password strength validators | Django auth |
| 11 | Rate limit login | Present + **Added** | Login lockout (5 failures / username + IP / 15 min) on web and API. **Added:** registration limited to 10 attempts per IP per hour; general API limits (60/min anonymous, 300/min per user) | `test_login_protection.*`, `test_security_hardening.RegistrationBotProtectionTests.test_registration_attempts_are_rate_limited_per_ip` |
| 12 | Add bot protection | **Added** | Registration honeypot field + minimum fill time via a signed timestamp (no external CAPTCHA service needed, works offline); refusals are audited. A CAPTCHA such as Cloudflare Turnstile could be added for a public deployment | `test_security_hardening.RegistrationBotProtectionTests` |
| 13 | Parameterize queries | Present | Django ORM only; no raw SQL anywhere in the code base | code search: no `.raw(`, `.extra(`, `cursor(` |
| 14 | Validate all input | Present | Django forms / DRF serializers with controlled choices; PDF validation; signed gateway messages validated for signature, age, reference, amount, currency | `test_documents.*`, `test_payments.NotificationSecurityTests` |
| 15 | Escape user content | Present + **Added** | Django template auto-escaping, no `|safe` / `mark_safe`. **Added:** strict Content-Security-Policy as a second layer (no inline scripts or styles allowed) | `test_security_hardening.SecurityHeaderTests` |
| 16 | Restrict file uploads | Present + **Added** | PDF only, signature + parser check, 5 MB, 500 pages, no passwords; stored outside any web-served folder. **Added:** requests over 6 MB are refused with HTTP 413 *before* being read | `test_documents.InspectDocumentTests`, `test_security_hardening.RequestSizeLimitTests` |
| 17 | Trim API responses | Present + **Added** | Serializers expose explicit fields only (no storage paths, no password data); admin data only for admins. **Added:** with `DEBUG=False` the API returns JSON only (no browsable HTML API) | `printing/serializers.py`, `chapify/settings.py` |
| 18 | Add security headers | Present + **Added** | Present: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, HSTS in HTTPS mode. **Added:** `Content-Security-Policy` (Django 6.0 built-in), `Permissions-Policy`, Subresource Integrity on the Bootstrap CDN stylesheet | `test_security_hardening.SecurityHeaderTests` |
| 19 | Force HTTPS | Present | `CHAPIFY_HTTPS=True`: HTTPS redirect, secure cookies, HSTS; verified by `check --deploy` in CI | CI step "Production security settings" |
| 20 | Scan dependencies | **Added** + Manual | `pip-audit` checks `requirements.txt` against known vulnerabilities in CI; Dependabot opens weekly update pull requests (pip and GitHub Actions). Dependabot alerts must be switched on in repository settings | `.github/workflows/tests.yml`, `.github/dependabot.yml` |

## Dependency scan result

The first `pip-audit` run (6 November 2026) found **34 published advisories in 4 pinned packages**:
Django 6.0.6, djangorestframework 3.17.1, sqlparse 0.5.5 and pypdf 6.21.0. They were upgraded to the
fixed releases (Django 6.0.8, djangorestframework 3.18.2, sqlparse 0.6.0, pypdf 6.21.4); the full
test suite passed unchanged and the next scan reported no known vulnerabilities. This shows why the
scan runs on every pull request: pinned versions silently become vulnerable over time.

## Owner actions (repository settings)

GitHub → repository **Settings** → **Advanced Security** (called *Code security* in some accounts):

1. **Dependabot alerts** → Enable.
2. **Dependabot security updates** → Enable.
3. **Secret Protection / Secret scanning** → Enable, and **Push protection** → Enable.

## Deliberately not done

- **Encrypting uploaded PDFs at rest.** The key would live on the same server as the files, so it
  mainly protects copies of the disk (backups, a stolen drive). Chapify instead minimises what it
  keeps: files are deleted as soon as the job is printed or cancelled, and abandoned files after
  24 hours. For a hosted deployment, full-disk encryption at the hosting level gives the same
  protection without application complexity.
- **Purging the old key from Git history** - see item 2.
- **External CAPTCHA** - would need third-party keys and internet access during the defence; the
  honeypot + timing check covers automated sign-ups at this scale.
