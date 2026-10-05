"""
Small cache-backed rate limits shared by sign-in, registration, password reset and the
assistant. Counters live in the cache (Redis in production, see settings.CACHES).
"""
from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    """The visitor's address: the proxy-supplied one when we sit behind our own Nginx."""
    if settings.TRUST_X_FORWARDED_FOR:
        first = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        if first:
            return first
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def hit(key, limit, window):
    """Count one event under ``key``; return False once more than ``limit`` happened in ``window`` seconds."""
    if cache.add(key, 1, window):
        return True
    try:
        return cache.incr(key) <= limit
    except ValueError:  # the key expired between add and incr
        cache.add(key, 1, window)
        return True


def exhausted(key, limit):
    """True when ``key`` has already reached ``limit`` (checked without counting)."""
    return cache.get(key, 0) >= limit


def clear(key):
    cache.delete(key)
