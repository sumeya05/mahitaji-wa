"""
Checkout and orders: checkout form, order placement, confirmation email, order pages and cancellation.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..cart import Cart
from ..forms import (
    CheckoutForm,
)
from ..models import (
    Address, MpesaTransaction, Order, OrderItem,
)
from ..services import MpesaError, initiate_stk_push as mpesa_stk_push
from ._common import form_errors, get_profile, json_error, json_ok, request_data

logger = logging.getLogger(__name__)


@login_required
def checkout(request):
    cart = Cart(request)
    if cart.is_empty:
        messages.info(request, "Your cart is empty. Add a few products before checking out.")
        return redirect('products')
    profile = get_profile(request.user)
    primary = profile.primary_address
    return render(request, 'core/checkout.html', {
        'cart': cart,
        'profile': profile,
        'addresses': profile.addresses.all(),
        'primary_address': primary,
        'mpesa_enabled': bool(settings.MPESA_CALLBACK_URL and settings.MPESA_CONSUMER_KEY),
    })


def _send_order_confirmation(order):
    if not order.email:
        return
    try:
        body = render_to_string('core/emails/order_confirmation.txt', {'order': order, 'site': settings.SITE_INFO})
        recipients = [order.email]
        if settings.ORDER_NOTIFICATION_EMAIL:
            recipients.append(settings.ORDER_NOTIFICATION_EMAIL)
        send_mail(f"Order {order.order_number} confirmed", body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
    except Exception:  # never let email problems break checkout
        logger.exception("Could not send confirmation for %s", order.order_number)


@login_required
@require_POST
def place_order(request):
    cart = Cart(request)
    if cart.is_empty:
        return json_error("Your cart is empty.", status=400)

    form = CheckoutForm(request_data(request))
    if not form.is_valid():
        return json_error("Please check the highlighted fields.", errors=form_errors(form))
    data = form.cleaned_data
    profile = get_profile(request.user)

    with transaction.atomic():
        order = Order.objects.create(
            order_number=Order.generate_order_number(),
            customer=profile,
            full_name=f"{data['first_name'].strip()} {data['last_name'].strip()}",
            email=data['email'],
            phone=data['phone'],
            address=data['address'].strip(),
            city=data['city'],
            notes=data.get('notes', '').strip(),
            payment_method=data['payment_method'],
            total_amount=cart.get_total_price(),
            status=Order.STATUS_PENDING,
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=item['product'], quantity=item['qty'], price_at_purchase=item['price'])
            for item in cart
        ])
        if not profile.phone_number:
            profile.phone_number = data['phone']
            profile.save(update_fields=['phone_number'])
        if data.get('save_address') or not profile.addresses.exists():
            Address.objects.update_or_create(
                customer=profile, is_primary=True,
                defaults={'label': 'Delivery Address', 'physical_address': order.address, 'city': order.city},
            )

    cart.clear()
    _send_order_confirmation(order)

    payment = {'sent': False, 'message': ''}
    if order.payment_method == Order.PAYMENT_MPESA:
        try:
            mpesa_stk_push(order, data['mpesa_phone'])
            payment = {'sent': True, 'message': 'Check your phone and enter your M-Pesa PIN to complete payment.'}
        except MpesaError as exc:
            payment = {'sent': False, 'message': str(exc)}

    return json_ok(
        order_number=order.order_number,
        order_id=order.id,
        payment_method=order.payment_method,
        payment=payment,
        redirect_url=reverse('order-success', args=[order.order_number]),
        status_url=reverse('check_payment_status', args=[order.order_number]),
    )


def _owned_order(request, order_number):
    return get_object_or_404(
        Order.objects.select_related('customer').prefetch_related('items__product'),
        order_number=order_number, customer__user=request.user,
    )


@login_required
def order_success(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-success.html', {
        'order': order,
        'mpesa_txn': getattr(order, 'mpesa_payment', None),
        'awaiting_payment': order.can_pay,
    })


@login_required
def order_detail(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-detail.html', {
        'order': order,
        'mpesa_txn': MpesaTransaction.objects.filter(order=order).first(),
        'awaiting_payment': order.can_pay,
    })


@login_required
@require_POST
def order_cancel(request, order_number):
    order = _owned_order(request, order_number)
    if not order.can_cancel:
        messages.error(request, "This order can no longer be cancelled. Please contact support.")
    else:
        order.status = Order.STATUS_CANCELLED
        order.save()
        messages.success(request, f"Order {order.order_number} has been cancelled.")
    return redirect('order_detail', order_number=order.order_number)


@login_required
def get_order_details(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), id=order_id, customer__user=request.user)
    return render(request, 'core/account/order_items_fragment.html', {'order': order})
