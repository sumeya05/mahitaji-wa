"""
Session cart: cart page, drawer fragment and the add / update / delete endpoints.
"""
import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from ..cart import Cart
from ..models import (
    Product,
)
from ._common import is_ajax, json_error, json_ok, request_data

logger = logging.getLogger(__name__)


def _cart_response(request, cart, message='', product=None):
    payload = {'cart': cart.summary(), 'message': message}
    if is_ajax(request):
        payload['drawer_html'] = render_to_string('partials/cart_drawer_items.html', {'cart': cart}, request=request)
        if product is not None:
            payload['product'] = {'id': product.id, 'name': product.name, 'qty': cart.quantity_of(product.id)}
        return json_ok(**payload)
    if message:
        messages.success(request, message)
    return redirect(request.META.get('HTTP_REFERER') or 'shopping-cart')


def shopping_cart(request):
    return render(request, 'core/shopping-cart.html', {'cart': Cart(request)})


def mini_cart(request):
    return render(request, 'partials/cart_drawer_items.html', {'cart': Cart(request)})


@require_POST
def cart_add(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = int(data.get('product_qty') or data.get('qty') or 1)
    except (TypeError, ValueError):
        return json_error("Invalid product.")
    product = get_object_or_404(Product, id=product_id, is_active=True)
    cart = Cart(request)
    cart.add(product, qty)
    return _cart_response(request, cart, f"{product.name} added to your cart.", product)


@require_POST
def cart_update(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = int(data.get('product_qty') or data.get('qty') or 1)
    except (TypeError, ValueError):
        return json_error("Invalid quantity.")
    cart = Cart(request)
    cart.update(product_id, qty)
    line_total = 0
    for item in cart:
        if item['product'].id == product_id:
            line_total = float(item['total_price'])
    if is_ajax(request):
        payload = {'cart': cart.summary(), 'line_total': line_total, 'product_id': product_id,
                   'drawer_html': render_to_string('partials/cart_drawer_items.html', {'cart': cart}, request=request)}
        return json_ok(**payload)
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
