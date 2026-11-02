from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    """Every account gets a Chapify profile.

    Accounts created with "createsuperuser" (or marked as staff at creation)
    become Chapify administrators; all other accounts are normal users.
    Roles can later be changed in the Django admin (Profiles).
    """
    if not created:
        return

    role = Profile.ROLE_ADMIN if (instance.is_superuser or instance.is_staff) else Profile.ROLE_USER
    Profile.objects.get_or_create(user=instance, defaults={"role": role})
