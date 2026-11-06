# Requirement-to-test traceability

Links every functional (FR) and non-functional (NFR) requirement from the thesis draft
(§1.3, Tables 1 and 2) to the code that implements it and the automated tests that verify it.

- Tests: `printing/tests/`, run with `python manage.py test`. Names are `module.Class.test`.
- CI runs the whole suite on every pull request (Windows + Linux, Python 3.12 / 3.13), plus
  `manage.py check`, `makemigrations --check` and `check --deploy --fail-level WARNING`.
- Status: **Met**, **Met (simulated)** = met with a simulated external system,
  **Partially met**, **Not verified** = not measured by automated tests.

## Functional requirements

| ID | Requirement | Implementation | Verified by | Status |
|---|---|---|---|---|
| FR-01 | User authentication | Django auth, `views.register`, `ChapifyLoginView`, DRF token auth | `test_workflow.ProfileTests.*`, `test_access_control.AuthenticationTests.*` | Met |
| FR-02 | Document upload and validation | `validators.inspect_uploaded_document` (PDF signature, parser, password, size, pages), private `MEDIA_ROOT` | `test_documents.InspectDocumentTests.*`, `test_documents.TrustedPricingTests.test_web_upload_rejects_invalid_file`, `…test_api_rejects_invalid_file` | Met (PDF only; draft §5.2 also lists DOCX) |
| FR-03 | Print parameter selection | `PrintSettings`, `PrintSettingsForm`, controlled choices | `test_workflow.CreateRequestTests.test_web_upload_and_settings_create_priced_request` | Met |
| FR-04 | Price calculation | `pricing.calculate_total_price` (Decimal, half-up), page count read from the PDF | `test_pricing_and_signing.PriceCalculationTests.*` (incl. §4.5 example = 4.00 EUR), `test_documents.TrustedPricingTests.*` | Met |
| FR-05 | Payment through an external gateway | `payments.build_checkout_url`, `mockgateway` (hosted checkout, signed session) | `test_payments.GatewayCheckoutFlowTests.*`, `test_payments.ApiPaymentTests.*` | Met (simulated gateway) |
| FR-06 | Payment confirmation / rejection handling | `payments.verify_notification`, `services.apply_payment_notification` (signature, age, reference, amount, idempotency) | `test_payments.NotificationSecurityTests.*`, `test_pricing_and_signing.SigningTests.*` | Met (simulated gateway) |
| FR-07 | Print job creation and forwarding | `services._queue_print_job`, `start_next_print_job`, `finish_print_job`, `run_print_simulator` | `test_printing_and_retention.PrintJobLifecycleTests.*` | Met (simulated print server) |
| FR-08 | Print status tracking | `services.ALLOWED_TRANSITIONS`, `transition()`; status page | `test_printing_and_retention.PrintJobLifecycleTests.*`, `test_workflow.EditAndCancelTests.*`, `test_payments.GatewayCheckoutFlowTests.test_declined_payment_can_be_retried` | Met |
| FR-09 | User print history | `views.request_history`, `/api/my/*` | `test_workflow.EditAndCancelTests.test_pages_render`, `test_access_control.ObjectOwnershipTests.test_lists_only_show_own_requests` | Met |
| FR-10 | Monitor print jobs | Admin overview print queue, failed jobs, *Print again*, printers page | `test_admin_management.RetryPrintJobTests.*`, `…PrinterManagementTests.test_offline_printers_receive_no_jobs`, `test_printing_and_retention.PrintJobLifecycleTests.test_admin_dashboard_button_processes_next_job` | Met |
| FR-11 | View transaction records | `views.admin_transactions`, `/api/admin/transactions/` | `test_admin_management.PrinterManagementTests.test_transactions_page_filters`, `test_access_control.AdministratorAccessTests.*` | Met |
| FR-12 | Maintain audit logs | `services.audit`, `signals` (login, failed login, logout), all workflow services | `test_admin_management.AuthenticationAuditTests.*`, `test_payments.NotificationSecurityTests.test_tampered_notification_is_refused_and_audited`, `test_login_protection.LoginLockoutTests.test_lockout_after_limit_even_with_correct_password` | Partially met: edits made in the Django admin tool are recorded only in Django's own admin log |
| FR-13 | Manage user accounts | `views.admin_users`, `services.set_account_status`, `set_role` | `test_admin_management.AccountBlockingTests.*`, `…RoleManagementTests.*` | Met (account details such as email are edited in the Django admin) |

## Non-functional requirements

| ID | Requirement | Implementation | Verified by | Status |
|---|---|---|---|---|
| NFR-01 | Security | Authentication, RBAC, CSRF, login lockout, session expiry, HTTPS settings for deployment | `test_access_control.*`, `test_login_protection.*`, CI `check --deploy` | Met for the implemented scope; HTTPS is configuration-only (not active on the local development server) |
| NFR-02 | Confidentiality | Object-level ownership checks (404 for other users' data), files outside any web-served folder, no card data | `test_access_control.ObjectOwnershipTests.*`, `test_workflow.CreateRequestTests.test_other_users_document_cannot_be_used` | Met |
| NFR-03 | Integrity | HMAC-signed gateway messages, atomic conditional status updates, unique confirmed payment, server-side page count | `test_payments.NotificationSecurityTests.*`, `test_payments.GatewayCheckoutFlowTests.test_amount_in_checkout_session_cannot_be_changed`, `test_workflow.CreateRequestTests.test_document_cannot_be_used_twice`, `test_documents.TrustedPricingTests.test_web_upload_stores_counted_pages_and_ignores_posted_value` | Met |
| NFR-04 | Availability | Not addressed beyond the development server | — | Not verified |
| NFR-05 | Usability | Three-step workflow, status badges, clear error messages | Manual walkthrough (`docs/USER_GUIDE.md`); page rendering in `test_workflow.EditAndCancelTests.test_pages_render` | Partially met: no usability study |
| NFR-06 | Performance | — | — (the full test suite runs in about 2 s, but that is not a performance measurement) | Not verified |
| NFR-07 | Maintainability | Service layer shared by web, API and commands; separate gateway and pricing modules; CI | CI on every pull request | Met |
| NFR-08 | Scalability | Relational model ready for PostgreSQL; SQLite used for the prototype | — | Not verified |
| NFR-09 | Auditability | As FR-12 | As FR-12 | Partially met (see FR-12) |
| NFR-10 | Data retention | Files deleted when a request is completed or cancelled; failed jobs keep files for the retry window; `cleanup_documents` | `test_printing_and_retention.RetentionTests.*`, `…PrintJobLifecycleTests.test_successful_print_completes_request_and_deletes_file` | Met |

## Security mechanisms and their tests

| Threat | Mechanism | Test |
|---|---|---|
| Payer confirms their own payment | No confirm endpoint; only signed gateway notifications change payment state | `test_payments.GatewayCheckoutFlowTests.test_user_cannot_confirm_own_payment` |
| Forged / tampered payment result | HMAC-SHA256 signature check | `test_payments.NotificationSecurityTests.test_tampered_notification_is_refused_and_audited`, `…test_notification_signed_with_wrong_secret_is_refused` |
| Replay of a payment result | Idempotent processing, conditional update, unique constraint | `test_payments.NotificationSecurityTests.test_replayed_notification_has_effect_only_once` |
| Old or misdirected notification | 15-minute age limit, reference and amount checks | `…test_expired_notification_is_refused`, `…test_amount_mismatch_is_refused`, `…test_unknown_reference_is_refused` |
| Price manipulation (amount or page count) | Signed checkout session; page count from the PDF | `test_payments.GatewayCheckoutFlowTests.test_amount_in_checkout_session_cannot_be_changed`, `test_documents.TrustedPricingTests.test_api_ignores_client_page_count` |
| Accessing another user's data (IDOR) | Ownership filter on every query | `test_access_control.ObjectOwnershipTests.*` |
| Privilege escalation | Single admin rule (`Profile.role`) for pages and API | `test_access_control.AdministratorAccessTests.*`, `test_admin_management.RoleManagementTests.test_normal_user_cannot_manage_accounts` |
| Password guessing | Lockout per username + IP (web and API) | `test_login_protection.LoginLockoutTests.*` |
| Blocked account still in use | `is_active` sync, sessions end, tokens deleted | `test_admin_management.AccountBlockingTests.*` |
| Malicious or fake uploads | PDF signature, parser, size and page limits | `test_documents.InspectDocumentTests.*` |
| Documents kept longer than needed | Deletion on completion/cancel, retention command | `test_printing_and_retention.RetentionTests.*` |
| Insecure production configuration | Start-up guard for development secrets; `check --deploy` in CI | CI step "Production security settings" |
| Script/style injection, clickjacking | Content-Security-Policy (own origin only, no CDN), X-Frame-Options | `test_security_hardening.SecurityHeaderTests.*` |
| Automated sign-ups | Honeypot, signed fill-time check, per-IP registration limit | `test_security_hardening.RegistrationBotProtectionTests.*` |
| Huge uploads exhausting disk/memory | 413 for bodies over 6 MB before reading | `test_security_hardening.RequestSizeLimitTests.*` |
| Vulnerable dependencies | `pip-audit` in CI, Dependabot weekly updates | CI step "Scan dependencies" |

## Known limitations

- The payment gateway and the print server are simulated; no real money is moved and nothing
  is printed. The gateway integration follows the hosted-checkout + signed-notification pattern
  of real providers, so a real provider could replace `mockgateway` behind `printing/payments.py`.
- No refunds: a payment confirmed for a job that finally fails is not refunded automatically.
- SQLite is used; login lockout counters are kept in memory and reset when the server restarts.
- Availability, performance and scalability (NFR-04, NFR-06, NFR-08) were not measured.
