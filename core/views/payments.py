"""
M-Pesa: STK push initiation, payment status polling and the Safaricom callback.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import (
    MpesaTransaction, Order,
)
from ..services import (
    MpesaError, initiate_stk_push as mpesa_stk_push, is_trusted_callback, process_stk_callback, refresh_payment,
)
from ._common import json_error, json_ok, request_data
from .checkout import _owned_order

logger = logging.getLogger(__name__)


@login_required
@require_POST
def initiate_stk_push(request):
    data = request_data(request)
    order_number = data.get('order_number')
    if order_number:
        order = _owned_order(request, order_number)
    else:
        order = get_object_or_404(Order, id=data.get('order_id'), customer__user=request.user)
    if order.is_paid:
        return json_error("This order is already paid.")
    if not order.can_pay:
        return json_error(f"This order is {order.get_status_display().lower()} and can no longer be paid.")
    try:
        mpesa_stk_push(order, data.get('phone') or order.phone)
    except MpesaError as exc:
        return json_error(str(exc), status=502)
    # Safaricom's request id stays on the server: it is what a payment confirmation is matched on.
    return json_ok(message="Check your phone and enter your M-Pesa PIN.")


def payment_status(order):
    """Where an order's payment stands: ``{'status': 'paid'|'failed'|'pending', ...}``.
    Shared by the website's polling endpoint and the mobile API."""
    txn = order.latest_payment
    if txn and not order.is_paid:
        # The callback does not always arrive (sandbox, tunnels, outages): ask Safaricom ourselves.
        txn = refresh_payment(txn)
        order.refresh_from_db()
    if order.is_paid:
        status = 'paid'
    elif order.status == Order.STATUS_FAILED:
        status = 'failed'
    else:
        status = 'pending'
    return {
        'status': status,
        'order_status': order.status,
        'receipt': txn.receipt_number if txn else None,
        'description': txn.response_description if txn else '',
    }


@login_required
@require_GET
def check_payment_status(request, order_number):
    return json_ok(**payment_status(_owned_order(request, order_number)))


@csrf_exempt
@require_POST
def mpesa_callback(request, token):
    """
    Safaricom posts the outcome of an STK push here. The URL we give Safaricom carries a
    secret token. A callback with the wrong token is still read (the token changes with
    SECRET_KEY, so this covers a misconfiguration), but nothing it says is applied until
    Safaricom has been asked and confirms it.
    """
    try:
        payload = json.loads(request.body or b'{}')
        txn, success = process_stk_callback(payload, trusted=is_trusted_callback(token))
        logger.info("M-Pesa callback for %s: %s", txn.order.order_number, 'success' if success else 'not paid')
    except MpesaTransaction.DoesNotExist:
        logger.warning("M-Pesa callback for unknown CheckoutRequestID: %s", request.body[:200])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Malformed M-Pesa callback: %s", exc)
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Malformed payload"}, status=400)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
