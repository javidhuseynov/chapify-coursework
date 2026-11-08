"""API endpoints for obtaining, listing and revoking API tokens."""

from django.contrib.auth import authenticate
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import api_tokens
from .login_protection import audit_blocked_attempt, client_ip, is_locked, lockout_message, register_failure, reset_failures
from .models import ApiToken
from .serializers import ErrorSerializer as ERROR



class TokenRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)
    name = serializers.CharField(
        required=False,
        max_length=100,
        help_text="Label for this client, shown to the user (e.g. 'Chapify mobile').",
    )


class IssuedTokenSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Shown only once. Send it as 'Authorization: Token <token>'.")
    token_type = serializers.CharField()
    id = serializers.IntegerField()
    name = serializers.CharField()
    expires_at = serializers.DateTimeField()


class ApiTokenSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField(help_text="True for the token used to make this request.")

    class Meta:
        model = ApiToken
        fields = ["id", "name", "key_prefix", "created_at", "expires_at", "last_used_at", "current"]

    def get_current(self, obj) -> bool:
        auth = self.context.get("auth")
        return isinstance(auth, ApiToken) and auth.pk == obj.pk


@extend_schema(
    tags=["Authentication"],
    summary="Log in and get an API token",
    description=(
        "Exchanges a username and password for a new API token. The token expires "
        "after the configured lifetime (7 days by default) and can be revoked. "
        "Repeated failed attempts lock the username for this IP address."
    ),
    request=TokenRequestSerializer,
    responses={
        201: IssuedTokenSerializer,
        400: OpenApiResponse(ERROR, description="Wrong username or password, or a disabled account."),
        429: OpenApiResponse(ERROR, description="Too many failed attempts."),
    },
    auth=[],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def obtain_token(request):
    serializer = TokenRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    username = serializer.validated_data["username"]
    ip = client_ip(request)

    if is_locked(username, ip):
        audit_blocked_attempt(username, ip)
        return Response({"detail": lockout_message()}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    user = authenticate(request, username=username, password=serializer.validated_data["password"])

    if user is None or not user.is_active:
        register_failure(username, ip)
        return Response(
            {"detail": "Unable to log in with the provided credentials."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reset_failures(username, ip)
    token, raw_token = api_tokens.issue_token(user, serializer.validated_data.get("name") or "API client")

    return Response(
        {
            "token": raw_token,
            "token_type": "Token",
            "id": token.id,
            "name": token.name,
            "expires_at": token.expires_at,
        },
        status=status.HTTP_201_CREATED,
    )


@extend_schema(
    tags=["Authentication"],
    summary="Log out this client",
    description="Revokes the token used to authenticate this request.",
    request=None,
    responses={204: None, 400: OpenApiResponse(ERROR, description="The request was not made with a token.")},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def revoke_current_token(request):
    if not isinstance(request.auth, ApiToken):
        return Response(
            {"detail": "This request was not authenticated with an API token."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    api_tokens.revoke_token(request.auth, request.user, "logged out by the client")
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["Authentication"],
    summary="List my active API tokens",
    responses={200: ApiTokenSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_tokens(request):
    tokens = api_tokens.active_tokens(request.user)
    return Response(ApiTokenSerializer(tokens, many=True, context={"auth": request.auth}).data)


@extend_schema(
    tags=["Authentication"],
    summary="Revoke one of my API tokens",
    request=None,
    responses={204: None, 404: OpenApiResponse(ERROR, description="No such active token.")},
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_token(request, token_id):
    token = api_tokens.active_tokens(request.user).filter(pk=token_id).first()

    if token is None:
        return Response({"detail": "No such active token."}, status=status.HTTP_404_NOT_FOUND)

    api_tokens.revoke_token(token, request.user, "revoked by the user")
    return Response(status=status.HTTP_204_NO_CONTENT)
