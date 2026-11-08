# Requirement-to-test traceability

Links every functional (FR) and non-functional (NFR) requirement from the thesis draft
(§1.3, Tables 1 and 2) to the code that implements it and the automated tests that verify it.

- Tests: `printing/tests/` and `print_station/tests/` (`python manage.py test`), and
  `gateway_service/checkout/tests/` (`python manage.py test` in `gateway_service`). Names are `module.Class.test`.
- CI runs the whole suite on every pull request (Windows + Linux, Python 3.12 / 3.13), plus
  `manage.py check`, `makemigrations --check` and `check --deploy --fail-level WARNING`.
- Status: **Met**, **Met (simulated)** = met with a simulated external system,
  **Partially met**, **Not verified** = not measured by automated tests.

## Functional requirements

| ID | Requirement | Implementation | Verified by | Status |
|---|---|---|---|---|
| FR-01 | User authentication | Django auth, `views.register`, `ChapifyLoginView`; API: expiring, revocable, hashed tokens (`api_tokens`, `api_auth`) | `test_workflow.ProfileTests.*`, `test_access_control.AuthenticationTests.*`, `test_api_tokens.*` | Met |
| FR-02 | Document upload and validation | `validators.inspect_uploaded_document` (PDF signature, parser, password, size, pages), private `MEDIA_ROOT` | `test_documents.InspectDocumentTests.*`, `test_documents.TrustedPricingTests.test_web_upload_rejects_invalid_file`, `…test_api_rejects_invalid_file` | Met (PDF only; draft §5.2 also lists DOCX) |
| FR-03 | Print parameter selection | `PrintSettings`, `PrintSettingsForm`, controlled choices | `test_workflow.CreateRequestTests.test_web_upload_and_settings_create_priced_request` | Met |
| FR-04 | Price calculation | `pricing.calculate_total_price` (Decimal, half-up), page count read from the PDF | `test_pricing_and_signing.PriceCalculationTests.*` (incl. §4.5 example = 4.00 EUR), `test_documents.TrustedPricingTests.*` | Met |
| FR-05 | Payment through an external gateway | `payment_gateways.ChapifyPayGateway` / `StripeGateway`, `payments.start_checkout`; separate gateway service `gateway_service/` (checkout sessions API, hosted card page) | `test_payments.CheckoutFlowTests.*`, `test_payments.ApiPaymentTests.*`, `test_payments.StripeAdapterTests.*`, `gateway_service: checkout.tests.test_gateway.*`, CI end-to-end payment in a browser | Met (separate test gateway; Stripe test mode not run against a live account) |
| FR-06 | Payment confirmation / rejection handling | Signed webhooks (`payment_gateways.verify_signature`), result read from the gateway API on return (`payments.confirm_on_return`), `services.apply_payment_notification` (reference, amount, idempotency) | `test_payments.WebhookTests.*`, `test_payments.CheckoutFlowTests.test_paid_on_return_even_without_webhook`, `test_pricing_and_signing.WebhookSignatureTests.*`, `checkout.tests.test_gateway.WebhookRetryTests.*` | Met (separate test gateway) |
| FR-07 | Print job creation and forwarding | `services._queue_print_job`, `start_next_print_job`; printer API (`printer_api`, `stations`) used by the separate print station program (`print_station/`); built-in simulator for printers without a station | `test_printing_and_retention.PrintJobLifecycleTests.*`, `test_print_station.PrinterApiTests.*`, `test_print_station.PrintStationProgramTests.*` (real program against a live server), `print_station.tests.test_device.*` | Met (simulated printer hardware) |
| FR-08 | Print status tracking | `services.ALLOWED_TRANSITIONS`, `transition()`; status page | `test_printing_and_retention.PrintJobLifecycleTests.*`, `test_workflow.EditAndCancelTests.*`, `test_payments.CheckoutFlowTests.test_declined_payment_can_be_retried` | Met |
| FR-09 | User print history | `views.request_history`, `/api/my/*` | `test_workflow.EditAndCancelTests.test_pages_render`, `test_access_control.ObjectOwnershipTests.test_lists_only_show_own_requests` | Met |
| FR-10 | Monitor print jobs | Admin overview print queue, failed jobs, *Print again*, printers page with station connection, paper and toner; watchdog for silent stations | `test_admin_management.RetryPrintJobTests.*`, `…PrinterManagementTests.test_offline_printers_receive_no_jobs`, `test_printing_and_retention.PrintJobLifecycleTests.test_admin_dashboard_button_processes_next_job`, `test_print_station.StationAdminTests.*`, `test_print_station.PrinterApiTests.test_watchdog_marks_silent_station_offline_and_fails_its_job` | Met |
| FR-11 | View transaction records | `views.admin_transactions`, `/api/admin/transactions/` | `test_admin_management.PrinterManagementTests.test_transactions_page_filters`, `test_access_control.AdministratorAccessTests.*` | Met |
| FR-12 | Maintain audit logs | `services.audit`, `signals` (login, failed login, logout), all workflow services | `test_admin_management.AuthenticationAuditTests.*`, `test_payments.WebhookTests.test_tampered_body_is_refused_and_audited`, `test_login_protection.LoginLockoutTests.test_lockout_after_limit_even_with_correct_password` | Partially met: edits made in the Django admin tool are recorded only in Django's own admin log |
| FR-13 | Manage user accounts | `views.admin_users`, `services.set_account_status`, `set_role` | `test_admin_management.AccountBlockingTests.*`, `…RoleManagementTests.*` | Met (account details such as email are edited in the Django admin) |

## Non-functional requirements

| ID | Requirement | Implementation | Verified by | Status |
|---|---|---|---|---|
| NFR-01 | Security | Authentication, RBAC, CSRF, login lockout, session expiry, HTTPS settings for deployment | `test_access_control.*`, `test_login_protection.*`, CI `check --deploy` | Met for the implemented scope; HTTPS is configuration-only (not active on the local development server) |
| NFR-02 | Confidentiality | Object-level ownership checks (404 for other users' data), files outside any web-served folder, no card data | `test_access_control.ObjectOwnershipTests.*`, `test_workflow.CreateRequestTests.test_other_users_document_cannot_be_used` | Met |
| NFR-03 | Integrity | Amount sent to the gateway server to server, HMAC-signed webhooks with timestamp, atomic conditional status updates, unique confirmed payment, server-side page count, SHA-256 check of downloaded print documents | `test_payments.WebhookTests.*`, `test_payments.CheckoutFlowTests.test_return_url_cannot_claim_a_payment`, `test_workflow.CreateRequestTests.test_document_cannot_be_used_twice`, `test_documents.TrustedPricingTests.test_web_upload_stores_counted_pages_and_ignores_posted_value` | Met |
| NFR-04 | Availability | Not addressed beyond the development server | — | Not verified |
| NFR-05 | Usability | Three-step workflow, status badges, clear error messages | Manual walkthrough (`docs/USER_GUIDE.md`); page rendering in `test_workflow.EditAndCancelTests.test_pages_render` | Partially met: no usability study |
| NFR-06 | Performance | — | — (the full test suite runs in about 2 s, but that is not a performance measurement) | Not verified |
| NFR-07 | Maintainability | Service layer shared by web, API and commands; gateway behind one interface (Chapify Pay / Stripe); OpenAPI schema validated in CI; three separately tested applications | CI on every pull request | Met |
| NFR-08 | Scalability | Relational model ready for PostgreSQL; SQLite used for the prototype | — | Not verified |
| NFR-09 | Auditability | As FR-12 | As FR-12 | Partially met (see FR-12) |
| NFR-10 | Data retention | Files deleted when a request is completed or cancelled; failed jobs keep files for the retry window; `cleanup_documents` | `test_printing_and_retention.RetentionTests.*`, `…PrintJobLifecycleTests.test_successful_print_completes_request_and_deletes_file` | Met |

## Security mechanisms and their tests

| Threat | Mechanism | Test |
|---|---|---|
| Payer confirms their own payment | No confirm endpoint; only the gateway (signed webhook or authenticated API) changes payment state; the return URL proves nothing | `test_payments.CheckoutFlowTests.test_user_cannot_confirm_own_payment`, `…test_return_url_cannot_claim_a_payment` |
| Forged / tampered payment result | HMAC-SHA256 webhook signature over timestamp and body | `test_payments.WebhookTests.test_tampered_body_is_refused_and_audited`, `…test_wrong_secret_or_missing_signature_is_refused`, `test_pricing_and_signing.WebhookSignatureTests.*` |
| Replay of a payment result | 5-minute signature window, idempotent processing, conditional update, unique constraint | `test_payments.WebhookTests.test_replayed_webhook_has_effect_only_once`, `…test_old_webhook_is_refused` |
| Misdirected payment result | Reference, amount, currency and session checks | `test_payments.WebhookTests.test_amount_mismatch_is_refused`, `…test_unknown_reference_is_refused`, `…test_webhook_for_superseded_attempt_is_refused` |
| Price manipulation (amount or page count) | Checkout session created server to server from the stored price; page count from the PDF | `test_payments.CheckoutFlowTests.test_checkout_session_is_created_server_to_server`, `test_documents.TrustedPricingTests.test_api_ignores_client_page_count` |
| Card data exposure | Card entered only on the gateway; gateway accepts only test cards, never re-displays the number or code, stores brand and last 4 digits only | `checkout.tests.test_gateway.CheckoutPageTests.test_only_test_cards_are_accepted_and_card_data_is_not_echoed_or_stored` |
| Real money moved by mistake | Stripe adapter accepts only `sk_test_` keys and rejects live-mode events | `test_payments.StripeAdapterTests.*` |
| Open redirect through the gateway | Return URLs limited to allowed merchant origins | `checkout.tests.test_gateway.MerchantApiTests.test_invalid_requests_are_refused` |
| Stolen or long-lived API token | Tokens expire, are stored hashed, can be revoked; password change and blocking revoke all | `test_api_tokens.*` |
| Rogue or stolen print station key | Per-printer key (hash stored, shown once, replaceable); a station sees only its own in-progress job; user tokens and printer keys are not interchangeable | `test_print_station.PrinterApiTests.test_keys_are_checked`, `…test_station_cannot_touch_another_printers_job`, `…test_new_key_replaces_the_old_one` |
| Damaged print download | SHA-256 and size in the job, checked by the station | `test_print_station.PrintStationProgramTests.*` |
| Accessing another user's data (IDOR) | Ownership filter on every query | `test_access_control.ObjectOwnershipTests.*` |
| Privilege escalation | Single admin rule (`Profile.role`) for pages and API | `test_access_control.AdministratorAccessTests.*`, `test_admin_management.RoleManagementTests.test_normal_user_cannot_manage_accounts` |
| Password guessing | Lockout per username + IP (web and API) | `test_login_protection.LoginLockoutTests.*` |
| Blocked account still in use | `is_active` sync, sessions end, API tokens revoked | `test_admin_management.AccountBlockingTests.*` |
| Malicious or fake uploads | PDF signature, parser, size and page limits | `test_documents.InspectDocumentTests.*` |
| Documents kept longer than needed | Deletion on completion/cancel, retention command | `test_printing_and_retention.RetentionTests.*` |
| Insecure production configuration | Start-up guard for development secrets; `check --deploy` in CI | CI step "Production security settings" |
| Script/style injection, clickjacking | Content-Security-Policy (own origin only, no CDN), X-Frame-Options | `test_security_hardening.SecurityHeaderTests.*` |
| Automated sign-ups | Honeypot, signed fill-time check, per-IP registration limit | `test_security_hardening.RegistrationBotProtectionTests.*` |
| Huge uploads exhausting disk/memory | 413 for bodies over 6 MB before reading | `test_security_hardening.RequestSizeLimitTests.*` |
| Vulnerable dependencies | `pip-audit` in CI, Dependabot weekly updates | CI step "Scan dependencies" |

## Known limitations

- The payment gateway (Chapify Pay) is a separate test gateway that accepts only test cards, and
  the printer hardware is simulated by the print station; no real money is moved and nothing is
  printed on paper. Both follow the protocols of real systems (hosted checkout with signed
  webhooks; a pull-based print agent), so a real provider (Stripe test mode is implemented) or a
  real printer driver could replace them. The Stripe adapter has not been run against a live
  Stripe test account.
- No refunds: a payment confirmed for a job that finally fails is not refunded automatically.
- SQLite is used; login lockout counters are kept in memory and reset when the server restarts.
- Availability, performance and scalability (NFR-04, NFR-06, NFR-08) were not measured.
