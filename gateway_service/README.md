# Chapify Pay – the test payment gateway

A **separate application** that plays the role of an external payment provider (like Stripe or
Paysera) for Chapify. It has its own Django project, database (`gateway.sqlite3`), cookies,
login and port (**8001**). Chapify does not import any of its code; the two talk only over HTTP.

No real money is moved: the card form accepts **only test card numbers**, and no card data is
stored (a payment keeps the card brand and the last four digits, as real gateways show merchants).

## How a payment works

```
 Payer's browser          Chapify (8000)                       Chapify Pay (8001)
 ---------------          --------------                       ------------------
 "Pay 4.00 EUR"  ──────►  create payment attempt
                          POST /v1/checkout/sessions  ───────► new session cs_test_...
                          (Authorization: Bearer sk_test_...)  {amount, currency, reference,
                                                                success_url, cancel_url}
                 ◄──────  redirect to the session's url
 card form       ─────────────────────────────────────────────► check test card → paid / declined
                                                                save payment (brand, last 4)
                          POST /payments/webhook/      ◄─────── signed webhook (retried until 2xx)
                          verify signature + time,             Chapify-Pay-Signature: t=..,v1=HMAC
                          apply result (idempotent)
                 ◄──────────────────────────────────────────── redirect to success_url?session_id=
 back on Chapify          GET /v1/checkout/sessions/<id> ────► result (server to server)
                          apply result if the webhook has not arrived yet
```

Chapify trusts a result only when it comes from the gateway: as a webhook with a valid signature
(HMAC-SHA256 of timestamp and body with the shared webhook secret, at most 5 minutes old), or from
the gateway's API called with Chapify's own secret key. The browser's return URL only tells Chapify
which session to ask about.

## Test cards

Any name, any future expiry date, any 3-digit security code.

| Card number | Result |
|---|---|
| 4242 4242 4242 4242 | Paid (Visa) |
| 5555 5555 5555 4444 | Paid (Mastercard) |
| 4000 0000 0000 0002 | Declined: card declined |
| 4000 0000 0000 9995 | Declined: insufficient funds |
| 4000 0000 0000 0069 | Declined: expired card |
| 4000 0000 0000 0127 | Declined: incorrect security code |

## Run (Command Prompt, from the project folder, with the virtual environment active)

```bat
cd gateway_service
python manage.py migrate
python manage.py runserver 127.0.0.1:8001
```

Or start everything with `start_demo.bat` in the project folder.

Merchant dashboard (sessions, payments, webhook deliveries with *Send again*):
http://127.0.0.1:8001/dashboard/ – create its login once with `python manage.py createsuperuser`
in this folder (separate from Chapify's accounts).

## Configuration

For a local demonstration the gateway reads the same `.env` file as Chapify (project folder), so
both sides use the same values. In a real deployment each party keeps its own configuration.

| Variable | Meaning | Default |
|---|---|---|
| `CHAPIFY_PAY_API_KEY` | Merchant secret key (Chapify → gateway API) | development value |
| `CHAPIFY_PAY_WEBHOOK_SECRET` | Signs webhooks (gateway → Chapify) | development value |
| `CHAPIFY_PAY_WEBHOOK_URL` | Where webhooks are sent | `http://127.0.0.1:8000/payments/webhook/` |
| `CHAPIFY_PAY_RETURN_ORIGINS` | Sites payers may be sent back to | `http://127.0.0.1:8000,http://localhost:8000` |
| `CHAPIFY_PAY_SECRET_KEY` | Django secret key of the gateway | development value |
| `CHAPIFY_PAY_DEBUG` | Debug mode | `True` |

Webhooks that fail are retried after 10 s, 1 min, 5 min, 30 min and 2 h (while someone uses the
gateway, or with `python manage.py deliver_webhooks --loop`).

## Tests

```bat
cd gateway_service
python manage.py test
```
