"""
Business services shared by the views, the admin and the signals:

* M-Pesa   - STK push, the Safaricom callback, and asking Safaricom for the outcome
* stock    - keeping the stock ledger in line with orders
* accounts - saving delivery addresses

Everything that talks to Safaricom lives here so the views stay small and the
integration can be mocked in tests.
"""
import base64
import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import throttle
from .forms import normalize_phone
from .models import Address, MpesaTransaction, Order, Product, StockLedger

logger = logging.getLogger(__name__)

STATUS_QUERY_INTERVAL = 9  # seconds between two status queries to Safaricom for one prompt


class MpesaError(Exception):
    """Raised when an STK push cannot be sent, or Safaricom cannot be asked about one."""


# ---------------------------------------------------------------------------
# M-Pesa
# ---------------------------------------------------------------------------
def mpesa_enabled():
    return bool(settings.MPESA_CALLBACK_URL and settings.MPESA_CONSUMER_KEY)


def callback_token():
    """Secret path segment of the callback URL given to Safaricom. A confirmation that
    arrives on that URL can only come from Safaricom, because nobody else is told it."""
    return salted_hmac('mahitaji.mpesa.callback', settings.SECRET_KEY).hexdigest()[:32]


def callback_url():
    return f"{settings.MPESA_CALLBACK_URL.rstrip('/')}/{callback_token()}/"


def is_trusted_callback(token):
    return bool(token) and constant_time_compare(token, callback_token())


def _client():
    # Imported lazily so the rest of the app never fails to import if the
    # daraja package is misconfigured.
    from django_daraja.mpesa.core import MpesaClient
    return MpesaClient()


def _shortcode():
    # Same choice django-daraja makes for STK pushes.
    return settings.MPESA_EXPRESS_SHORTCODE if settings.MPESA_ENVIRONMENT == 'sandbox' else settings.MPESA_SHORTCODE


def stk_amount(order):
    """M-Pesa only moves whole shillings."""
    return int(Decimal(order.total_amount).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


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

    amount = stk_amount(order)
    if amount < 1:
        raise MpesaError("The order total must be at least KSh 1 to pay via M-Pesa.")

    # One prompt at a time: a second one while the first is still on the phone only confuses.
    throttle_key = f'mpesa-prompt-{order.pk}'
    if settings.MPESA_PROMPT_INTERVAL and not cache.add(throttle_key, 1, settings.MPESA_PROMPT_INTERVAL):
        raise MpesaError("A payment prompt was sent a moment ago. Check your phone, or try again in a few seconds.")
    # ...and only so many per customer per hour: the prompt goes to whatever number they typed.
    if settings.MPESA_PROMPTS_PER_HOUR and not throttle.hit(f'mpesa-prompts:customer:{order.customer_id}',
                                                           settings.MPESA_PROMPTS_PER_HOUR, 60 * 60):
        cache.delete(throttle_key)
        raise MpesaError("You have requested several payment prompts in the last hour. Please wait a while, "
                         "or choose Cash on Delivery.")
    if msisdn != normalize_phone(order.phone):
        logger.info("STK push for order %s goes to %s, not the order's number", order.order_number, msisdn)

    account_reference = order.order_number[:12]
    try:
        response = _client().stk_push(msisdn, amount, account_reference, "Mahitaji Order", callback_url())
    except Exception as exc:  # network / credential problems
        cache.delete(throttle_key)
        logger.exception("STK push failed for order %s", order.order_number)
        raise MpesaError("We could not reach M-Pesa right now. Please try again in a moment.") from exc

    checkout_id = getattr(response, 'checkout_request_id', None)
    if not checkout_id:
        cache.delete(throttle_key)
        description = getattr(response, 'error_message', None) or getattr(response, 'response_description', None)
        logger.error("STK push rejected for order %s: %s", order.order_number, description)
        raise MpesaError(description or "M-Pesa rejected the payment request. Please try again.")

    # Earlier attempts are kept: the customer may still approve an older prompt.
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


def query_stk_status(txn):
    """
    Ask Safaricom what became of an STK push (the callback does not always arrive,
    and an unauthenticated callback is never taken at its word).

    Returns ``(paid, description)``: paid is True when the customer paid, False when the
    payment failed or was cancelled, None while there is no outcome yet. Raises MpesaError
    when Safaricom cannot be reached.
    """
    from django_daraja.mpesa.utils import api_base_url, mpesa_access_token

    shortcode = _shortcode()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(f'{shortcode}{settings.MPESA_PASSKEY}{timestamp}'.encode()).decode()
    try:
        response = requests.post(
            api_base_url() + 'mpesa/stkpushquery/v1/query',
            json={'BusinessShortCode': shortcode, 'Password': password, 'Timestamp': timestamp,
                  'CheckoutRequestID': txn.checkout_request_id},
            headers={'Authorization': 'Bearer ' + mpesa_access_token()},
            timeout=settings.MPESA_TIMEOUT,
        )
        body = response.json()
    except Exception as exc:  # network, credentials, non-JSON answer
        raise MpesaError(f"Could not ask M-Pesa about {txn.checkout_request_id}: {exc}") from exc

    code = str(body.get('ResultCode', ''))
    description = body.get('ResultDesc') or body.get('errorMessage') or f'HTTP {response.status_code}'
    if code == '0':
        return True, description
    if code in ('', '4999'):  # no result yet: the prompt is unanswered, or we are being rate limited
        return None, description
    return False, description


def _parse_mpesa_date(value):
    """M-Pesa sends 20240521143012 (YYYYMMDDHHMMSS) as an int."""
    try:
        naive = datetime.strptime(str(value), '%Y%m%d%H%M%S')
    except (TypeError, ValueError):
        return timezone.now()
    return timezone.make_aware(naive, timezone.get_default_timezone())


def record_payment_outcome(txn, paid, description='', *, result_code=None, receipt=None, amount=None,
                           phone=None, paid_on=None):
    """
    Store the outcome of one STK push and move its order on. Safe to call twice:
    a transaction that already succeeded is never changed again.
    """
    with db_transaction.atomic():
        txn = MpesaTransaction.objects.select_for_update().select_related('order').get(pk=txn.pk)
        if txn.is_success:
            return txn
        order = txn.order
        txn.response_description = description or txn.response_description
        if paid:
            txn.is_success = True
            txn.result_code = 0
            txn.receipt_number = receipt or txn.receipt_number
            if amount is not None:
                txn.amount = amount
            if phone:
                txn.phone_number = str(phone)
            txn.transaction_date = paid_on or timezone.now()
            txn.save()
            if order.status == Order.STATUS_CANCELLED:
                logger.warning("Order %s was cancelled but M-Pesa payment %s arrived: refund needed",
                               order.order_number, txn.receipt_number or txn.checkout_request_id)
            order.mark_paid(txn.transaction_date)
            return txn

        txn.is_success = False
        txn.result_code = result_code if result_code is not None else 1
        txn.save()
        # Only the newest prompt decides whether the order is waiting or failed.
        newest = order.mpesa_payments.order_by('-created_at', '-pk').first()
        if order.status == Order.STATUS_PENDING and not order.is_paid and newest and newest.pk == txn.pk:
            order.status = Order.STATUS_FAILED
            order.save()
        return txn


def process_stk_callback(payload, trusted=False):
    """
    Apply an STK callback payload to the matching transaction and order.

    ``trusted`` says the callback arrived on the secret URL only Safaricom knows. An
    untrusted callback decides nothing by itself, whether it claims success or failure:
    Safaricom is asked, and only its answer is recorded. If Safaricom cannot be reached,
    or has no outcome yet, the prompt simply stays pending.

    Returns (transaction, success). Raises KeyError/LookupError for malformed
    or unknown callbacks so the view can answer Safaricom appropriately.
    """
    callback = payload['Body']['stkCallback']
    checkout_id = callback['CheckoutRequestID']
    result_code = int(callback.get('ResultCode', 1))
    result_desc = callback.get('ResultDesc', '')

    txn = MpesaTransaction.objects.select_related('order').get(checkout_request_id=checkout_id)
    if txn.is_success:
        return txn, True  # a repeat of a callback we already handled

    metadata = {item.get('Name'): item.get('Value') for item in callback.get('CallbackMetadata', {}).get('Item', [])}
    amount = None
    if metadata.get('Amount') is not None:
        try:
            amount = Decimal(str(metadata['Amount']))
        except InvalidOperation:
            amount = None
    underpaid = amount is not None and amount < txn.amount

    if not trusted:
        try:
            paid, description = query_stk_status(txn)
        except MpesaError as exc:
            logger.warning("Unverified M-Pesa callback for %s left pending: %s", txn.order.order_number, exc)
            return txn, False
        if paid is None:
            logger.warning("Unverified M-Pesa callback for %s has no outcome at Safaricom yet (%s)",
                           txn.order.order_number, description)
            return txn, False
        if paid is False:
            logger.warning("Unverified M-Pesa callback for %s: Safaricom reports no payment (%s)",
                           txn.order.order_number, description)
            return record_payment_outcome(txn, False, description), False
        if result_code != 0 or underpaid:
            # Safaricom says paid but the callback claimed otherwise: trust Safaricom, not the
            # callback's figures. The receipt details arrive with the next status check.
            logger.warning("Unverified M-Pesa callback for %s contradicted by Safaricom, which reports payment",
                           txn.order.order_number)
            return record_payment_outcome(txn, True, description), True

    if result_code != 0:
        return record_payment_outcome(txn, False, result_desc, result_code=result_code), False

    if underpaid:
        logger.error("M-Pesa callback for %s reports KSh %s, expected KSh %s: not marking paid",
                     txn.order.order_number, amount, txn.amount)
        return txn, False

    txn = record_payment_outcome(
        txn, True, result_desc, receipt=metadata.get('MpesaReceiptNumber'), amount=amount,
        phone=metadata.get('PhoneNumber'), paid_on=_parse_mpesa_date(metadata.get('TransactionDate')),
    )
    return txn, True


def refresh_payment(txn):
    """While a prompt has no outcome, ask Safaricom for it (at most every few seconds)."""
    if txn.is_success or txn.result_code is not None or not mpesa_enabled():
        return txn
    if not cache.add(f'mpesa-status-query-{txn.pk}', 1, STATUS_QUERY_INTERVAL):
        return txn
    try:
        paid, description = query_stk_status(txn)
    except MpesaError as exc:
        logger.warning("M-Pesa status query failed for %s: %s", txn.order.order_number, exc)
        return txn
    if paid is None:
        return txn
    return record_payment_outcome(txn, paid, description)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
def sync_order_stock(order):
    """
    Bring the stock ledger in line with ``order``: an order holds its quantities from
    the moment it is placed until it is cancelled. Calling this again changes nothing,
    and it corrects the ledger after an order's lines are edited in the admin.

    Only products whose stock is tracked (stock has been received for them) are booked.
    """
    references = [f"ORDER-{order.order_number}", f"RESTOCK-{order.order_number}"]
    wanted = {}
    if order.status != Order.STATUS_CANCELLED:
        for item in order.items.all():
            wanted[item.product_id] = wanted.get(item.product_id, 0) + item.quantity

    booked = {
        row['product']: -(row['total'] or 0)
        for row in StockLedger.objects.filter(reference_number__in=references)
        .order_by().values('product').annotate(total=Sum('quantity'))
    }
    tracked = set(
        StockLedger.objects.filter(product__in=set(wanted) | set(booked), quantity__gt=0)
        .values_list('product', flat=True)
    )
    for product_id in set(wanted) | set(booked):
        want, have = wanted.get(product_id, 0), booked.get(product_id, 0)
        if product_id not in tracked:
            want = min(want, have)  # untracked lines are not booked; an old booking is still released
        difference = want - have    # > 0: hold more stock, < 0: give some back
        if difference:
            StockLedger.objects.create(
                product_id=product_id,
                transaction_type='SALE' if difference > 0 else 'ADJUSTMENT',
                quantity=-difference,
                reference_number=references[0],
            )


def lock_products(product_ids):
    """Serialise competing checkouts for the same products (inside a transaction)."""
    return list(Product.objects.select_for_update().filter(id__in=product_ids).order_by('id'))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def save_address(profile, text, city=None, label=None, make_primary=False):
    """Save a delivery address, reusing an identical one; the address book is never overwritten."""
    text = (text or '').strip()
    city = (city or '').strip() or 'Nairobi'
    address = profile.addresses.filter(physical_address__iexact=text, city__iexact=city).first()
    if address is None:
        address = Address(
            customer=profile, physical_address=text, city=city, is_primary=False,
            label=(label or '').strip()[:50] or f'Address {profile.addresses.count() + 1}',
        )
    if make_primary:
        address.is_primary = True
    address.save()
    return address
