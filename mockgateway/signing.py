"""Signed message format shared by Chapify and the mock payment gateway.

In a real integration this module is the gateway's SDK / documented signature
scheme. A message is a JSON object encoded as base64url and followed by an
HMAC-SHA256 signature computed with a secret shared between the merchant
(Chapify) and the gateway:

    <base64url(json)>.<hex(hmac_sha256(secret, base64url(json)))>

Anyone can read the message, but nobody without the secret can create or
modify one without the signature check failing.

This module has no Django dependency so that it can be unit tested on its own.
"""

import base64
import hashlib
import hmac
import json
import time


class BadSignature(Exception):
    """The message was modified, malformed or signed with another secret."""


class ExpiredSignature(BadSignature):
    """The message is older than the allowed maximum age."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _signature(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()


def sign(data: dict, secret: str, issued_at: int | None = None) -> str:
    """Return a signed token for ``data``. Adds an ``issued_at`` timestamp."""
    if not secret:
        raise ValueError("A signing secret is required.")

    payload = dict(data)
    payload["issued_at"] = int(time.time()) if issued_at is None else int(issued_at)

    body = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return f"{body}.{_signature(body, secret)}"


def unsign(token: str, secret: str, max_age: int | None = None, now: int | None = None) -> dict:
    """Verify ``token`` and return its data.

    Raises BadSignature if the token is malformed or the signature does not
    match, and ExpiredSignature if it is older than ``max_age`` seconds.
    """
    if not secret:
        raise ValueError("A signing secret is required.")

    if not token or not isinstance(token, str) or "." not in token:
        raise BadSignature("Malformed signed message.")

    body, _, received_signature = token.rpartition(".")

    try:
        expected_signature = _signature(body, secret)
    except UnicodeEncodeError as exc:
        raise BadSignature("Malformed signed message.") from exc

    if not hmac.compare_digest(received_signature, expected_signature):
        raise BadSignature("Signature verification failed.")

    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadSignature("Malformed signed message.") from exc

    if not isinstance(payload, dict):
        raise BadSignature("Malformed signed message.")

    if max_age is not None:
        issued_at = payload.get("issued_at")
        current_time = int(time.time()) if now is None else int(now)

        if not isinstance(issued_at, int) or current_time - issued_at > max_age:
            raise ExpiredSignature("Signed message has expired.")

    return payload
