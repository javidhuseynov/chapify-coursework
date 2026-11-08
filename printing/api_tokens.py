"""Expiring, revocable API tokens (used by API clients such as a mobile app).

A token is a random secret shown to the client exactly once. Chapify stores
only its SHA-256 hash, together with an expiry time. Clients send it as

    Authorization: Token <token>        (or: Authorization: Bearer <token>)

A token stops working when it expires, when the user revokes it ("log out
this device"), when the user changes their password, or when an
administrator blocks the account.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from .models import ApiToken, AuditLog

TOKEN_PREFIX = "chp_"
ACCEPTED_KEYWORDS = (b"token", b"bearer")
# last_used_at is refreshed at most this often, to avoid a database write per request.
LAST_USED_RESOLUTION = timedelta(minutes=1)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _audit(event_type, description, user):
    AuditLog.objects.create(event_type=event_type, description=description, user=user)


def issue_token(user, name="API client"):
    """Create a token for ``user``. Returns (ApiToken, raw_token).

    The raw token is returned only here; it cannot be recovered later.
    When the user already has the maximum number of active tokens, the
    oldest ones are revoked.
    """
    name = (name or "API client").strip()[:100] or "API client"
    raw_token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = timezone.now()

    with transaction.atomic():
        token = ApiToken.objects.create(
            user=user,
            name=name,
            key_prefix=raw_token[:12],
            key_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(hours=settings.API_TOKEN_TTL_HOURS),
        )

        active = ApiToken.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=now)
        surplus = list(active.order_by("-created_at")[settings.API_TOKENS_PER_USER:])
        if surplus:
            ApiToken.objects.filter(pk__in=[t.pk for t in surplus]).update(revoked_at=now)

        _audit(
            AuditLog.EVENT_API_TOKEN_CREATED,
            f"API token '{token.name}' ({token.key_prefix}...) issued to {user.username}, "
            f"valid until {token.expires_at:%Y-%m-%d %H:%M} UTC.",
            user,
        )

    return token, raw_token


def revoke_token(token, actor, reason):
    """Revoke one token. Returns True if it was active."""
    updated = ApiToken.objects.filter(pk=token.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())

    if updated:
        _audit(
            AuditLog.EVENT_API_TOKEN_REVOKED,
            f"API token '{token.name}' ({token.key_prefix}...) of {token.user.username} revoked: {reason}.",
            actor,
        )

    return bool(updated)


def revoke_all_tokens(user, actor, reason):
    """Revoke every active token of ``user``. Returns the number revoked."""
    count = ApiToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())

    if count:
        _audit(
            AuditLog.EVENT_API_TOKEN_REVOKED,
            f"{count} API token(s) of {user.username} revoked: {reason}.",
            actor,
        )

    return count


def active_tokens(user):
    return ApiToken.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now())


def purge_old_tokens(now=None, keep_days=30):
    """Delete tokens that expired or were revoked more than ``keep_days`` ago."""
    cutoff = (now or timezone.now()) - timedelta(days=keep_days)
    deleted, _ = ApiToken.objects.filter(expires_at__lt=cutoff).delete()
    deleted_revoked, _ = ApiToken.objects.filter(revoked_at__lt=cutoff).delete()
    return deleted + deleted_revoked


class ExpiringTokenAuthentication(BaseAuthentication):
    """DRF authentication class for ApiToken."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()

        if not parts or parts[0].lower() not in ACCEPTED_KEYWORDS:
            return None  # not a token request; other authentication classes may apply

        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid token header.")

        try:
            raw_token = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed("Invalid token header.")

        token = (
            ApiToken.objects
            .select_related("user", "user__profile")
            .filter(key_hash=hash_token(raw_token))
            .first()
        )

        if token is None or token.revoked_at is not None:
            raise exceptions.AuthenticationFailed("Invalid or revoked token.")

        now = timezone.now()

        if token.expires_at <= now:
            raise exceptions.AuthenticationFailed("Token has expired. Log in again to get a new one.")

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("This account is disabled.")

        if token.last_used_at is None or now - token.last_used_at > LAST_USED_RESOLUTION:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)

        return token.user, token

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when the token is missing or invalid.
        return "Token"
