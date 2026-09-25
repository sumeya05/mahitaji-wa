"""
Payment services: a thin, well-behaved wrapper around django-daraja (Safaricom M-Pesa).

Everything that talks to Safaricom lives here so the views stay small and the
integration can be mocked in tests.
"""
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from .forms import normalize_phone
from .models import MpesaTransaction, Order

logger = logging.getLogger(__name__)


class MpesaError(Exception):
    """Raised when an STK push cannot be sent."""


def _client():
    # Imported lazily so the rest of the app never fails to import if the
    # daraja package is misconfigured.
    from django_daraja.mpesa.core import MpesaClient
    return MpesaClient()


def initiate_stk_push(order, phone):
    """
    Send an M-Pesa STK push for ``order`` to ``phone`` and record the attempt.

    Returns the MpesaTransaction. Raises MpesaError with a customer-friendly
    message on failure.
    """
    msisdn = normalize_phone(phone)
    if not msisdn:
        raise MpesaError("Enter a valid Safaricom number, e.g. 0712 345 678.")
    if not settings.MPESA_CALLBACK_URL:
        raise MpesaError("M-Pesa payments are not configured yet. Please choose Cash on Delivery.")

    amount = int(round(order.total_amount))
    if amount < 1:
        raise MpesaError("The order total must be at least KSh 1 to pay via M-Pesa.")

    account_reference = order.order_number[:12]
    try:
        response = _client().stk_push(msisdn, amount, account_reference, "Mahitaji Order", settings.MPESA_CALLBACK_URL)
    except Exception as exc:  # network / credential problems
        logger.exception("STK push failed for order %s", order.order_number)
        raise MpesaError("We could not reach M-Pesa right now. Please try again in a moment.") from exc

    checkout_id = getattr(response, 'checkout_request_id', None)
    if not checkout_id:
        description = getattr(response, 'error_message', None) or getattr(response, 'response_description', None)
        logger.error("STK push rejected for order %s: %s", order.order_number, description)
        raise MpesaError(description or "M-Pesa rejected the payment request. Please try again.")

    MpesaTransaction.objects.filter(order=order).delete()
    txn = MpesaTransaction.objects.create(
        order=order,
        checkout_request_id=checkout_id,
        merchant_request_id=getattr(response, 'merchant_request_id', '') or '',
        amount=amount,
        phone_number=msisdn,
        is_success=False,
        response_description=getattr(response, 'response_description', '') or '',
    )
    update_fields = []
    if order.payment_method != Order.PAYMENT_MPESA:
        order.payment_method = Order.PAYMENT_MPESA
        update_fields.append('payment_method')
    if order.status == Order.STATUS_FAILED:
        # A fresh prompt means we are waiting again; keep the status truthful.
        order.status = Order.STATUS_PENDING
        update_fields.append('status')
    if update_fields:
        order.save(update_fields=update_fields)
    return txn


def _parse_mpesa_date(value):
    """M-Pesa sends 20240521143012 (YYYYMMDDHHMMSS) as an int."""
    try:
        naive = datetime.strptime(str(value), '%Y%m%d%H%M%S')
    except (TypeError, ValueError):
        return timezone.now()
    return timezone.make_aware(naive, timezone.get_default_timezone())


def process_stk_callback(payload):
    """
    Apply an STK callback payload to the matching transaction and order.

    Returns (transaction, success). Raises KeyError/LookupError for malformed
    or unknown callbacks so the view can answer Safaricom appropriately.
    """
    callback = payload['Body']['stkCallback']
    checkout_id = callback['CheckoutRequestID']
    result_code = int(callback.get('ResultCode', 1))
    result_desc = callback.get('ResultDesc', '')

    with db_transaction.atomic():
        txn = MpesaTransaction.objects.select_for_update().select_related('order').get(checkout_request_id=checkout_id)
        order = txn.order
        txn.response_description = result_desc

        if result_code == 0:
            metadata = {item.get('Name'): item.get('Value') for item in callback.get('CallbackMetadata', {}).get('Item', [])}
            txn.is_success = True
            txn.receipt_number = metadata.get('MpesaReceiptNumber') or txn.receipt_number
            if metadata.get('Amount') is not None:
                txn.amount = metadata['Amount']
            if metadata.get('PhoneNumber'):
                txn.phone_number = str(metadata['PhoneNumber'])
            txn.transaction_date = _parse_mpesa_date(metadata.get('TransactionDate'))
            txn.save()
            if order.status in (Order.STATUS_PENDING, Order.STATUS_FAILED):
                order.status = Order.STATUS_PAID
                order.save()
            return txn, True

        txn.is_success = False
        txn.save()
        if order.status == Order.STATUS_PENDING:
            order.status = Order.STATUS_FAILED
            order.save()
        return txn, False
