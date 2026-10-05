"""
Request middleware specific to the shop.
"""
import secrets
import time

from django.conf import settings
from django.contrib.auth import logout

SEEN_KEY = '_staff_seen'


class StaffSessionTimeoutMiddleware:
    """
    Sign staff out after settings.STAFF_SESSION_IDLE_SECONDS without a request. Customers
    keep their long-lived sessions (their cart lives there); accounts that can open the admin
    should not stay signed in on a shared or lost device.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and user.is_staff:
            now = int(time.time())
            last_seen = request.session.get(SEEN_KEY)
            if last_seen and now - last_seen > settings.STAFF_SESSION_IDLE_SECONDS:
                logout(request)  # the admin then redirects to its sign-in page
            elif not last_seen or now - last_seen > 60:
                request.session[SEEN_KEY] = now  # written at most once a minute
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """
    Send a Content-Security-Policy on storefront pages. Scripts may only come from this
    origin or from inline blocks that carry this request's nonce (``request.csp_nonce``),
    so a stray piece of HTML can never run script even if escaping slips somewhere.
    The admin and the browsable API are exempt (settings.CSP_EXEMPT_PREFIXES).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        if any(request.path.startswith(prefix) for prefix in settings.CSP_EXEMPT_PREFIXES):
            return response
        if 'Content-Security-Policy' in response or not response.get('Content-Type', '').startswith('text/html'):
            return response
        directives = []
        for name, sources in settings.CSP_DIRECTIVES.items():
            values = list(sources)
            if name == 'script-src':
                values.append(f"'nonce-{request.csp_nonce}'")
            directives.append(f"{name} {' '.join(values)}".strip())
        response['Content-Security-Policy'] = '; '.join(directives)
        return response
