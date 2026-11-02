from .permissions import is_chapify_admin


def chapify_roles(request):
    return {"is_chapify_admin": is_chapify_admin(getattr(request, "user", None))}
