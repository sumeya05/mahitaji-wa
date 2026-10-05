"""
Shared helpers used by every view module: JSON responses, request parsing, profile lookup and safe redirects.
"""
import json
import logging

from django.http import JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import (
    CustomerProfile,
)

logger = logging.getLogger(__name__)


def is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
        'application/json' in request.headers.get('accept', '')


def json_ok(**payload):
    payload.setdefault('ok', True)
    return JsonResponse(payload)


def json_error(message, status=400, errors=None):
    return JsonResponse({'ok': False, 'error': message, 'errors': errors or {}}, status=status)


def form_errors(form):
    return {field: [str(e) for e in errs] for field, errs in form.errors.items()}


def request_data(request):
    """Accept JSON bodies as well as regular form posts."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body or b'{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}  # a JSON list or string carries no fields
    return request.POST


def get_profile(user):
    profile, _ = CustomerProfile.objects.get_or_create(
        user=user, defaults={'phone_number': '', 'contact_person': user.get_full_name()}
    )
    # Populate both sides of the one-to-one so later ``user.customerprofile`` /
    # ``profile.user`` accesses (tier lookup, templates) do not re-query.
    user.customerprofile = profile
    return profile


def safe_next_url(request, fallback='dashboard'):
    candidate = request.POST.get('next') or request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return reverse(fallback)


def back_url(request, fallback='home'):
    """The page a form was posted from, if it is on this site (the Referer header is not trusted blindly)."""
    candidate = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return reverse(fallback)
