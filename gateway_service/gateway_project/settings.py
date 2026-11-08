"""Settings of Chapify Pay, the test payment gateway.

This is a separate Django project with its own database (gateway.sqlite3),
its own cookies and its own port (8001). For a local demonstration it reads
the same .env file as Chapify (the project folder above), so the API key and
webhook secret agree on both sides. In a real deployment each party would
keep its own configuration.
"""

import os
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path):
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")
_load_env(BASE_DIR.parent / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def env_list(name, default):
    value = os.environ.get(name)
    return default if value is None else [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = env("CHAPIFY_PAY_SECRET_KEY", "django-insecure-gateway-development-key-change-me")
DEBUG = env("CHAPIFY_PAY_DEBUG", "True").lower() in ("1", "true", "yes", "on")
ALLOWED_HOSTS = env_list("CHAPIFY_PAY_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "checkout",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "gateway_project.urls"
WSGI_APPLICATION = "gateway_project.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "gateway.sqlite3",
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Chapify and the gateway both run on 127.0.0.1 during a demonstration, and
# browsers do not separate cookies by port: use different cookie names.
SESSION_COOKIE_NAME = "chapifypay_sessionid"
CSRF_COOKIE_NAME = "chapifypay_csrftoken"
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# --- The merchant (Chapify) -------------------------------------------------------
MERCHANT = {
    "id": "chapify",
    "name": "Chapify",
    # Chapify sends this key to create checkout sessions (Authorization: Bearer ...).
    "api_key": env("CHAPIFY_PAY_API_KEY", "sk_test_local-development-key-change-me"),
    # Used to sign webhooks; Chapify verifies them with the same secret.
    "webhook_secret": env("CHAPIFY_PAY_WEBHOOK_SECRET", "whsec_local-development-secret-change-me"),
    "webhook_url": env("CHAPIFY_PAY_WEBHOOK_URL", "http://127.0.0.1:8000/payments/webhook/"),
}
# Payers may only be sent back to these sites (no open redirect).
ALLOWED_RETURN_ORIGINS = env_list(
    "CHAPIFY_PAY_RETURN_ORIGINS", ["http://127.0.0.1:8000", "http://localhost:8000"]
)

CHECKOUT_SESSION_MINUTES = 30
CURRENCIES = ("EUR",)
MIN_AMOUNT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000.00")
WEBHOOK_TIMEOUT_SECONDS = 5
WEBHOOK_RETRY_DELAYS = [10, 60, 300, 1800, 7200]  # seconds after attempts 1, 2, 3, ...

SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.NONE],
    # After paying, the browser is redirected back to the merchant.
    "form-action": [CSP.SELF, *ALLOWED_RETURN_ORIGINS],
    "frame-ancestors": [CSP.NONE],
}

if not DEBUG and ("change-me" in SECRET_KEY or "change-me" in MERCHANT["api_key"]
                  or "change-me" in MERCHANT["webhook_secret"]):
    raise ImproperlyConfigured(
        "Set CHAPIFY_PAY_SECRET_KEY, CHAPIFY_PAY_API_KEY and CHAPIFY_PAY_WEBHOOK_SECRET before running with DEBUG off."
    )
