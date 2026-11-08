"""Webhook signatures: header "Chapify-Pay-Signature: t=<unix time>,v1=<hex>".

v1 = HMAC-SHA256(webhook secret, "<t>.<raw request body>"), the same scheme as
Stripe's. The merchant recomputes it and rejects old timestamps (replays).
"""

import hashlib
import hmac
import time


def signature_header(secret, body: bytes, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"
