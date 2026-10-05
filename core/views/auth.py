"""
Authentication: login, registration, logout and the password reset flow.
"""
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import (
    RegisterForm,
)
from .. import throttle
from ._common import form_errors, is_ajax, json_error, json_ok, safe_next_url

logger = logging.getLogger(__name__)

# Sign-in attempts (counters live in the cache):
#  - after LOGIN_FAILURE_LIMIT failures for one account from one address, that pair is paused
#    for the rest of the window;
#  - after LOGIN_ADDRESS_LIMIT failures from one address against any accounts, the address is
#    paused, which stops password spraying across many accounts.
LOGIN_FAILURE_LIMIT = 8
LOGIN_ADDRESS_LIMIT = 30
LOGIN_FAILURE_WINDOW = 15 * 60
# New accounts and password-reset emails per address per hour.
REGISTER_LIMIT, REGISTER_WINDOW = 10, 60 * 60
RESET_LIMIT, RESET_WINDOW = 5, 60 * 60

TOO_MANY = "Too many sign-in attempts. Please wait 15 minutes, or reset your password."


def _login_throttle_keys(request, login_input):
    address = throttle.client_ip(request)
    return f'login-failures:{address}:{login_input.lower()[:150]}', f'login-failures:{address}'


def _too_many(request, template, context, message):
    if is_ajax(request):
        return json_error(message, status=429)
    messages.error(request, message)
    return render(request, template, context, status=429)


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        login_input = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        pair_key, address_key = _login_throttle_keys(request, login_input)
        if throttle.exhausted(pair_key, LOGIN_FAILURE_LIMIT) or throttle.exhausted(address_key, LOGIN_ADDRESS_LIMIT):
            return _too_many(request, 'core/auth/login.html', {'next': request.GET.get('next', '')}, TOO_MANY)

        username = login_input
        if '@' in login_input:
            matched = User.objects.filter(email__iexact=login_input).order_by('id').first()
            if matched:
                username = matched.username
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            throttle.clear(pair_key)
            login(request, user)
            if not request.POST.get('remember_me'):
                request.session.set_expiry(0)
            next_url = safe_next_url(request)
            if is_ajax(request):
                return json_ok(redirect_url=next_url)
            return redirect(next_url)

        throttle.hit(pair_key, LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW)
        throttle.hit(address_key, LOGIN_ADDRESS_LIMIT, LOGIN_FAILURE_WINDOW)
        logger.warning("Failed sign-in for %r from %s", login_input[:150], throttle.client_ip(request))
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
            if not throttle.hit(f'register:{throttle.client_ip(request)}', REGISTER_LIMIT, REGISTER_WINDOW):
                return _too_many(request, 'core/auth/register.html', {'form': form},
                                 "Too many accounts have been created from your connection. Please try again in an hour.")
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
            if not throttle.hit(f'password-reset:{throttle.client_ip(request)}', RESET_LIMIT, RESET_WINDOW):
                return _too_many(request, 'core/auth/password_reset.html', {},
                                 "Too many reset emails have been requested. Please wait an hour and try again.")
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
