"""Protection against password guessing (OWASP Authentication Cheat Sheet).

After LOGIN_FAILURE_LIMIT failed attempts for the same username from the same
IP address, further attempts are refused for LOGIN_LOCKOUT_SECONDS, even with
the correct password. Counting per username + IP (not per username alone)
stops an attacker from locking a real user out from elsewhere.

The counters live in Django's cache (in memory by default), so they reset
when the server restarts - acceptable for this system's scale.
"""

import hashlib

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache

from .models import AuditLog


def client_ip(request):
    if request is None:
        return "unknown"
    return request.META.get("REMOTE_ADDR", "unknown")


def _key(username, ip):
    digest = hashlib.sha256(f"{username.strip().lower()}|{ip}".encode("utf-8")).hexdigest()
    return f"chapify:login-failures:{digest}"


def is_locked(username, ip):
    return cache.get(_key(username, ip), 0) >= settings.LOGIN_FAILURE_LIMIT


def register_failure(username, ip):
    key = _key(username, ip)
    cache.add(key, 0, timeout=settings.LOGIN_LOCKOUT_SECONDS)
    try:
        failures = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=settings.LOGIN_LOCKOUT_SECONDS)
        failures = 1
    # Restart the lockout window with every failure.
    cache.touch(key, timeout=settings.LOGIN_LOCKOUT_SECONDS)
    return failures


def reset_failures(username, ip):
    cache.delete(_key(username, ip))


def lockout_message():
    minutes = max(1, settings.LOGIN_LOCKOUT_SECONDS // 60)
    return f"Too many failed login attempts. Try again in {minutes} minutes."


def audit_blocked_attempt(username, ip):
    AuditLog.objects.create(
        event_type=AuditLog.EVENT_LOGIN_FAILED,
        description=f"Login attempt for username '{username[:150]}' from {ip} refused: too many failed attempts.",
    )


class ThrottledAuthenticationForm(AuthenticationForm):
    """Django's login form with the lockout rule above."""

    def clean(self):
        username = self.cleaned_data.get("username") or ""
        ip = client_ip(self.request)

        if username and is_locked(username, ip):
            audit_blocked_attempt(username, ip)
            raise forms.ValidationError(lockout_message(), code="locked")

        try:
            cleaned_data = super().clean()
        except forms.ValidationError:
            if username:
                register_failure(username, ip)
            raise

        reset_failures(username, ip)
        return cleaned_data
