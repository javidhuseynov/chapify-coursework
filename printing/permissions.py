"""Single rule for administrator access (RBAC).

A user is a Chapify administrator when their Profile role is ADMIN. This rule
is used by the web pages, the REST API and the templates. (Access to the
built-in Django admin at /admin/ additionally requires Django's own
"staff status" flag; that tool is for development and data inspection.)
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Profile


def is_chapify_admin(user):
    if not user or not user.is_authenticated:
        return False

    profile = getattr(user, "profile", None)
    return profile is not None and profile.role == Profile.ROLE_ADMIN


def chapify_admin_required(view_func):
    """Web view decorator: login required, then ADMIN role required (403)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        if not is_chapify_admin(request.user):
            raise PermissionDenied("Administrator privileges are required.")

        return view_func(request, *args, **kwargs)

    return wrapper


class IsChapifyAdmin(BasePermission):
    message = "Administrator privileges are required."

    def has_permission(self, request, view):
        return is_chapify_admin(request.user)
