"""
Help desk and company pages, the contact form and newsletter sign-up.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import (
    ContactForm, NewsletterForm,
)
from ..models import (
    NewsletterSubscriber,
)
from ._common import back_url, form_errors, is_ajax, json_error, json_ok, request_data

logger = logging.getLogger(__name__)


def pickups(request):
    return render(request, 'core/pages/pickups.html')


def payment_info(request):
    return render(request, 'core/pages/payment_info.html')


def returns(request):
    return render(request, 'core/pages/returns.html')


def faqs(request):
    return render(request, 'core/pages/faqs.html')


def terms(request):
    return render(request, 'core/pages/terms.html')


def about(request):
    return render(request, 'core/pages/about.html')


def statement(request):
    return render(request, 'core/pages/statement.html')


def location(request):
    return render(request, 'core/pages/location.html')


@require_http_methods(["GET", "POST"])
def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            message = form.save()
            try:
                send_mail(
                    f"[Mahitaji] {message.get_inquiry_type_display()} from {message.full_name}",
                    f"{message.message}\n\nFrom: {message.full_name} <{message.email}> {message.phone}\nBusiness: {message.business_name}",
                    settings.DEFAULT_FROM_EMAIL, [settings.SITE_INFO['email']], fail_silently=True,
                )
            except Exception:
                logger.exception("Contact email failed")
            if is_ajax(request):
                return json_ok(message="Thanks! Our team will get back to you within one business day.")
            messages.success(request, "Thanks! Our team will get back to you within one business day.")
            return redirect('contact')
        if is_ajax(request):
            return json_error("Please check the highlighted fields.", errors=form_errors(form))
    else:
        initial = {}
        if request.user.is_authenticated:
            profile = getattr(request.user, 'customerprofile', None)
            initial = {'full_name': request.user.get_full_name(), 'email': request.user.email,
                       'business_name': profile.business_name if profile else '', 'phone': profile.phone_number if profile else ''}
        form = ContactForm(initial=initial)
    return render(request, 'core/pages/contact.html', {'form': form})


@require_POST
def newsletter_subscribe(request):
    form = NewsletterForm(request_data(request))
    if form.is_valid():
        NewsletterSubscriber.objects.get_or_create(email=form.cleaned_data['email'])
        msg = "You're on the list. Expect offers and stock alerts in your inbox."
        if is_ajax(request):
            return json_ok(message=msg)
        messages.success(request, msg)
    else:
        if is_ajax(request):
            return json_error("Enter a valid email address.", errors=form_errors(form))
        messages.error(request, "Enter a valid email address.")
    return redirect(back_url(request))
