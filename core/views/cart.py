"""
Session cart: cart page, drawer fragment, the add / update / delete endpoints and the coupon form.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from ..cart import Cart
from ..models import (
    Coupon, Product, plain_number,
)
from ._common import back_url, is_ajax, json_error, json_ok, request_data

logger = logging.getLogger(__name__)


def _drawer_html(request, cart):
    return render_to_string('partials/cart_drawer_items.html', {'cart': cart}, request=request)


def _cart_response(request, cart, message='', product=None, **extra):
    if is_ajax(request):
        payload = {'cart': cart.summary(), 'message': message, 'drawer_html': _drawer_html(request, cart), **extra}
        if product is not None:
            payload['product'] = {'id': product.id, 'name': product.name, 'qty': cart.quantity_of(product.id)}
        return json_ok(**payload)
    if message:
        messages.success(request, message)
    return redirect(back_url(request, 'shopping-cart'))


def _quantity(data, default=None):
    """The quantity sent by the browser; 0 is a real value (it removes the line)."""
    raw = data.get('product_qty')
    if raw in (None, ''):
        raw = data.get('qty')
    if raw in (None, ''):
        if default is None:
            raise ValueError("quantity missing")
        return default
    return int(raw)


def shopping_cart(request):
    return render(request, 'core/shopping-cart.html', {'cart': Cart(request)})


def mini_cart(request):
    return render(request, 'partials/cart_drawer_items.html', {'cart': Cart(request)})


@require_POST
def cart_add(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = max(_quantity(data, default=1), 1)
    except (TypeError, ValueError):
        return json_error("Invalid product.")
    product = get_object_or_404(Product.objects.with_stock(), id=product_id, is_active=True)
    if not product.is_purchasable:
        return json_error(f"{product.name} has no price yet. Please contact us to order it.")
    if product.stock_state == 'out':
        return json_error(f"{product.name} is out of stock.")

    cart = Cart(request)
    before = cart.quantity_of(product.id)
    now = cart.add(product, qty)
    if now <= before:
        return json_error(f"You already have all {now} of {product.name} that we have in stock.")
    if now < before + qty:
        message = f"Only {product.available_stock} of {product.name} in stock: your cart now has {now}."
    else:
        message = f"{product.name} added to your cart."
    return _cart_response(request, cart, message, product)


@require_POST
def cart_update(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = _quantity(data)
    except (TypeError, ValueError):
        return json_error("Invalid quantity.")
    cart = Cart(request)
    kept = cart.update(product_id, qty)
    message = ''
    if 0 < kept < qty:
        message = f"Only {kept} left in stock."
    elif kept == 0 and qty > 0:
        message = "That product is no longer available and was removed from your cart."
    line_total = next((float(item['total_price']) for item in cart if item['product'].id == product_id), 0)
    if is_ajax(request):
        return json_ok(cart=cart.summary(), line_total=line_total, product_id=product_id, item_qty=kept,
                       message=message, drawer_html=_drawer_html(request, cart))
    if message:
        messages.info(request, message)
    return redirect('shopping-cart')


@require_POST
def cart_delete(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
    except (TypeError, ValueError):
        return json_error("Invalid product.")
    cart = Cart(request)
    cart.delete(product_id)
    return _cart_response(request, cart, "Item removed from your cart.")


@require_POST
def apply_coupon(request):
    """Apply a coupon code to the cart, or drop it when ``remove`` is posted."""
    data = request_data(request)
    cart = Cart(request)
    code = str(data.get('code') or '').strip()
    if data.get('remove'):
        cart.set_coupon(None)
        ok, message = True, "Coupon removed."
    else:
        coupon = Coupon.usable(code)
        if coupon:
            cart.set_coupon(coupon)
            ok, message = True, f"Coupon {coupon.code} applied: {plain_number(coupon.percent)}% off your order."
        elif not code:
            ok, message = False, "Enter a coupon code."
        else:
            ok, message = False, f"“{code}” is not a valid coupon code."

    if is_ajax(request):
        if not ok:
            return json_error(message)
        return json_ok(message=message, cart=cart.summary(), drawer_html=_drawer_html(request, cart))
    (messages.success if ok else messages.error)(request, message)
    return redirect(back_url(request, 'shopping-cart'))
