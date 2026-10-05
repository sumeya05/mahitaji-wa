"""
Authentication: login, registration, logout and the password reset flow.
"""
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import (
    RegisterForm,
)
from ._common import form_errors, is_ajax, json_error, json_ok, safe_next_url

logger = logging.getLogger(__name__)

# Sign-in attempts: after this many failures for one account from one address, sign-in for
# that pair is paused for the rest of the window. (Counters live in the cache.)
LOGIN_FAILURE_LIMIT = 8
LOGIN_FAILURE_WINDOW = 15 * 60


def _login_throttle_key(request, login_input):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    address = forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
    return f'login-failures:{address}:{login_input.lower()[:150]}'


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        login_input = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        throttle_key = _login_throttle_key(request, login_input)
        if cache.get(throttle_key, 0) >= LOGIN_FAILURE_LIMIT:
            error_msg = "Too many sign-in attempts. Please wait 15 minutes, or reset your password."
            if is_ajax(request):
                return json_error(error_msg, status=429)
            messages.error(request, error_msg)
            return render(request, 'core/auth/login.html', {'next': request.GET.get('next', '')}, status=429)

        username = login_input
        if '@' in login_input:
            matched = User.objects.filter(email__iexact=login_input).order_by('id').first()
            if matched:
                username = matched.username
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            cache.delete(throttle_key)
            login(request, user)
            if not request.POST.get('remember_me'):
                request.session.set_expiry(0)
            next_url = safe_next_url(request)
            if is_ajax(request):
                return json_ok(redirect_url=next_url)
            return redirect(next_url)

        if not cache.add(throttle_key, 1, LOGIN_FAILURE_WINDOW):
            try:
                cache.incr(throttle_key)
            except ValueError:  # expired between add and incr
                cache.add(throttle_key, 1, LOGIN_FAILURE_WINDOW)
        error_msg = "We couldn't sign you in with those details. Check your email/username and password."
        if is_ajax(request):
            return json_error(error_msg, status=400)
        messages.error(request, error_msg)

    return render(request, 'core/auth/login.html', {'next': request.GET.get('next', '')})


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to Mahitaji, {user.first_name}! Your account is ready.")
            if is_ajax(request):
                return json_ok(redirect_url=safe_next_url(request))
            return redirect(safe_next_url(request))
        if is_ajax(request):
            return json_error("Please fix the highlighted fields.", errors=form_errors(form))
    else:
        form = RegisterForm()
    return render(request, 'core/auth/register.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    if is_ajax(request):
        return json_ok(redirect_url=reverse('home'))
    messages.info(request, "You have been signed out.")
    return redirect('home')


@require_http_methods(["GET", "POST"])
def custom_password_reset(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name='core/auth/password_reset_email.html',
                subject_template_name='core/auth/password_reset_subject.txt',
            )
            # Always behave the same, so the form can't be used to enumerate accounts.
            if is_ajax(request):
                return json_ok(redirect_url=reverse('password_reset_done'))
            return redirect('password_reset_done')
        if is_ajax(request):
            return json_error("Enter a valid email address.", errors=form_errors(form))
    return render(request, 'core/auth/password_reset.html')


@require_http_methods(["GET", "POST"])
def custom_password_reset_confirm(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist, UnicodeDecodeError):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'core/auth/password_reset_invalid.html', status=400)

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            if is_ajax(request):
                return json_ok(redirect_url=reverse('password_reset_complete'))
            return redirect('password_reset_complete')
        if is_ajax(request):
            return json_error("Please check the password requirements.", errors=form_errors(form))
    else:
        form = SetPasswordForm(user)
    return render(request, 'core/auth/password_reset_confirm.html', {'form': form})


def password_reset_done(request):
    return render(request, 'core/auth/password_reset_done.html')


def password_reset_complete(request):
    return render(request, 'core/auth/password_reset_complete.html')
