from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditLog, Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    """Every account gets a Chapify profile.

    Accounts created with "createsuperuser" (or marked as staff at creation)
    become Chapify administrators; all other accounts are normal users.
    """
    if created:
        role = Profile.ROLE_ADMIN if (instance.is_superuser or instance.is_staff) else Profile.ROLE_USER
        Profile.objects.get_or_create(user=instance, defaults={"role": role})
        return

    # An account deactivated directly in the Django admin counts as blocked.
    if not instance.is_active:
        Profile.objects.filter(user=instance, account_status=Profile.STATUS_ACTIVE).update(
            account_status=Profile.STATUS_BLOCKED
        )


@receiver(post_save, sender=Profile)
def sync_account_status(sender, instance, **kwargs):
    """Profile.account_status is the source of truth for whether a user may sign in.

    Django refuses logins, ends existing sessions and rejects API tokens for
    users whose ``is_active`` flag is False, so a BLOCKED or DELETED profile
    is mirrored into that flag. (``update()`` does not send signals, so this
    cannot loop.)
    """
    should_be_active = instance.account_status == Profile.STATUS_ACTIVE
    get_user_model().objects.filter(pk=instance.user_id).exclude(is_active=should_be_active).update(
        is_active=should_be_active
    )


def _client_address(request):
    if request is None:
        return "unknown address"
    return request.META.get("REMOTE_ADDR", "unknown address")


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    AuditLog.objects.create(
        user=user,
        event_type=AuditLog.EVENT_LOGIN_SUCCESS,
        description=f"User {user.username} logged in from {_client_address(request)}.",
    )


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user is not None:
        AuditLog.objects.create(
            user=user,
            event_type=AuditLog.EVENT_LOGOUT,
            description=f"User {user.username} logged out.",
        )


@receiver(user_login_failed)
def audit_failed_login(sender, credentials, request=None, **kwargs):
    # Django masks the password in "credentials"; only the username is logged.
    username = str(credentials.get("username", ""))[:150]
    AuditLog.objects.create(
        event_type=AuditLog.EVENT_LOGIN_FAILED,
        description=f"Failed login attempt for username '{username}' from {_client_address(request)}.",
    )
