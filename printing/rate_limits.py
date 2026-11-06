"""Small fixed-window rate limiter on top of Django's cache (no extra dependency)."""

import hashlib

from django.core.cache import cache


def _key(scope, identity):
    digest = hashlib.sha256(f"{scope}|{identity}".encode("utf-8")).hexdigest()
    return f"chapify:rate:{scope}:{digest}"


def hit(scope, identity, limit, window_seconds):
    """Count one event. Returns True if the caller is still within the limit."""
    key = _key(scope, identity)
    cache.add(key, 0, timeout=window_seconds)
    try:
        count = cache.incr(key)
    except ValueError:  # entry expired between add() and incr()
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    return count <= limit
