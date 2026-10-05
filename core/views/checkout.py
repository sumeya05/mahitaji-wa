"""
Checkout and orders: checkout form, order placement, confirmation email, order pages, the order PDF and cancellation.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import mailer
from ..cart import Cart
from ..forms import (
    CheckoutForm,
)
from ..models import (
    Order, OrderItem,
)
from ..order_document import PdfUnavailable, build_order_pdf
from ..services import (
    MpesaError, initiate_stk_push as mpesa_stk_push, lock_products, mpesa_enabled, save_address, sync_order_stock,
)
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
        'mpesa_enabled': mpesa_enabled(),
        'stock_problems': cart.stock_problems(),
    })


def _send_order_confirmation(order):
    if not order.email:
        return
    try:
        body = render_to_string('core/emails/order_confirmation.txt', {'order': order, 'site': settings.SITE_INFO})
        # The shop's own copy goes as a blind copy, so customers never see the internal address.
        bcc = [settings.ORDER_NOTIFICATION_EMAIL] if settings.ORDER_NOTIFICATION_EMAIL else []
        message = EmailMessage(f"Order {order.order_number} confirmed", body, settings.DEFAULT_FROM_EMAIL,
                               [order.email], bcc=bcc)
        mailer.send(message, label=f"confirmation for {order.order_number}")
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
        # Two customers checking out the last cartons at once are handled one after the other.
        lock_products([item['product'].id for item in cart])
        cart = Cart(request)  # re-read prices and stock now that the products are locked
        if cart.is_empty:
            return json_error("Your cart is empty.", status=400)
        unpriced = [item['product'].name for item in cart if item['price'] <= 0]
        if unpriced:
            return json_error(f"{', '.join(unpriced)} cannot be ordered online yet. Please remove it and contact us for a price.")
        problems = cart.stock_problems()
        if problems:
            return json_error(' '.join(problems) + " Please update your cart.")

        coupon = cart.coupon
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
            total_amount=cart.total,
            vat_amount=cart.vat,
            coupon_code=coupon.code if coupon else '',
            discount_percent=cart.discount_percent,
            discount_amount=cart.discount,
            status=Order.STATUS_PENDING,
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=item['product'], quantity=item['qty'], price_at_purchase=item['price'])
            for item in cart
        ])
        sync_order_stock(order)  # the order holds its stock from now until it is cancelled

        if not profile.phone_number:
            profile.phone_number = data['phone']
            profile.save(update_fields=['phone_number'])
        if data.get('save_address') or not profile.addresses.exists():
            save_address(profile, order.address, order.city, make_primary=not profile.addresses.exists())

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
        Order.objects.select_related('customer').prefetch_related('items__product__unit_of_measure', 'mpesa_payments'),
        order_number=order_number, customer__user=request.user,
    )


@login_required
def order_success(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-success.html', {
        'order': order,
        'mpesa_txn': order.latest_payment,
        'awaiting_payment': order.can_pay,
    })


@login_required
def order_detail(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-detail.html', {
        'order': order,
        'mpesa_txn': order.latest_payment,
        'awaiting_payment': order.can_pay,
    })


@login_required
def order_pdf(request, order_number):
    """The Sales Order of one of the customer's own orders, as a PDF download."""
    order = _owned_order(request, order_number)
    try:
        pdf = build_order_pdf(order)
    except PdfUnavailable:
        logger.error("Order PDF requested but ReportLab is not installed (pip install -r requirements.txt)")
        messages.error(request, "The PDF is not available right now. Please contact us for a copy of this order.")
        return redirect('order_detail', order_number=order.order_number)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{order.order_number}.pdf"'
    return response


@login_required
@require_POST
def order_cancel(request, order_number):
    order = _owned_order(request, order_number)
    if not order.can_cancel:
        messages.error(request, "This order can no longer be cancelled. Please contact support.")
    else:
        order.status = Order.STATUS_CANCELLED
        order.save()  # the stock it was holding is released by the status-change signal
        messages.success(request, f"Order {order.order_number} has been cancelled.")
    return redirect('order_detail', order_number=order.order_number)


@login_required
@require_POST
def order_pay_on_delivery(request, order_number):
    """Switch an unpaid M-Pesa order to cash on delivery, e.g. after a cancelled or failed prompt."""
    order = _owned_order(request, order_number)
    if not order.can_pay:
        messages.error(request, "This order's payment method can no longer be changed. Please contact support.")
    else:
        order.payment_method = Order.PAYMENT_COD
        order.status = Order.STATUS_PENDING  # a failed prompt no longer matters
        order.save()
        messages.success(request, f"Order {order.order_number} will be paid on delivery. "
                                  f"Have KSh {order.total_amount:,.0f} ready for the driver.")
    return redirect('order_detail', order_number=order.order_number)


@login_required
def get_order_details(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product__unit_of_measure'), id=order_id, customer__user=request.user)
    return render(request, 'core/account/order_items_fragment.html', {'order': order})
