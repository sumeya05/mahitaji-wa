from decimal import Decimal
from django.conf import settings
from .models import Product

class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('session_cart')
        if not cart:
            cart = self.session['session_cart'] = {}
        self.cart = cart

    def add(self, product, quantity=1):
        product_id = str(product.id)
        if product_id not in self.cart:
            # Store price as a STRING, never a Decimal
            self.cart[product_id] = {'price': str(product.retail_price), 'qty': 0}
        
        self.cart[product_id]['qty'] += int(quantity)
        self.session.modified = True

    def delete(self, product_id):
        product_id = str(product_id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.session.modified = True

    def update(self, product_id, qty):
        product_id = str(product_id)
        if product_id in self.cart:
            self.cart[product_id]['qty'] = int(qty)
            self.session.modified = True

    def get_total_price(self):
        # Keep this as Decimal for math, but DO NOT save this value into self.session
        return sum(Decimal(item['price']) * item['qty'] for item in self.cart.values())

    # core/cart.py
    def clear(self):
        # Remove from session entirely
        if settings.CART_SESSION_ID in self.session:
            del self.session[settings.CART_SESSION_ID]
        
        # Reset local variable
        self.cart = {}
        self.session.modified = True

    def __len__(self):
        return sum(item['qty'] for item in self.cart.values())

    def __iter__(self):
        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids)
        
        # Create a copy so we don't modify the session-stored dictionary
        cart_copy = self.cart.copy()
        
        for product in products:
            cart_copy[str(product.id)]['product'] = product

        for item in cart_copy.values():
            # Convert to Decimal ONLY for the current loop/template display
            item['price'] = Decimal(item['price'])
            item['total_price'] = item['price'] * item['qty']
            yield item