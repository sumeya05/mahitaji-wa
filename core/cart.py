"""
Session based shopping cart.

The session only stores ``{product_id: quantity}``. Prices are always resolved
from the product at read time using the customer's price tier, so a wholesaler
who logs in after filling the cart as a guest is charged wholesale prices, and
price changes in the catalogue are always reflected.
"""
from decimal import Decimal

from django.conf import settings

from .models import PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE, Product

MAX_QTY_PER_LINE = 999


def price_tier_for(user):
    if user is not None and user.is_authenticated:
        profile = getattr(user, 'customerprofile', None)
        if profile and profile.is_wholesaler:
            return PRICE_TIER_WHOLESALE
    return PRICE_TIER_RETAIL


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.user = getattr(request, 'user', None)
        self.tier = price_tier_for(self.user)
        cart = self.session.get(settings.CART_SESSION_ID)
        if cart is None:
            cart = self.session[settings.CART_SESSION_ID] = {}
        # Migrate the legacy format ({'price': .., 'qty': ..}) to plain quantities.
        migrated = False
        for key, value in list(cart.items()):
            if isinstance(value, dict):
                cart[key] = int(value.get('qty', 1))
                migrated = True
        if migrated:
            self.session.modified = True
        self.cart = cart
        self._products = None

    # --- mutations ---------------------------------------------------------
    def add(self, product, quantity=1):
        product_id = str(product.id)
        quantity = max(1, int(quantity))
        self.cart[product_id] = min(self.cart.get(product_id, 0) + quantity, MAX_QTY_PER_LINE)
        self._save()

    def update(self, product_id, qty):
        product_id = str(product_id)
        qty = int(qty)
        if qty <= 0:
            self.delete(product_id)
            return
        if product_id in self.cart:
            self.cart[product_id] = min(qty, MAX_QTY_PER_LINE)
            self._save()

    def delete(self, product_id):
        product_id = str(product_id)
        if product_id in self.cart:
            del self.cart[product_id]
            self._save()

    def clear(self):
        self.session[settings.CART_SESSION_ID] = {}
        self.cart = self.session[settings.CART_SESSION_ID]
        self._save()

    def _save(self):
        self._products = None
        self.session.modified = True

    # --- reads -------------------------------------------------------------
    def _load_products(self):
        if self._products is None:
            ids = [int(pk) for pk in self.cart.keys()]
            products = Product.objects.filter(id__in=ids, is_active=True).with_relations()
            self._products = {str(p.id): p for p in products}
            # Drop lines whose product no longer exists / was deactivated.
            stale = [pk for pk in self.cart if pk not in self._products]
            if stale:
                for pk in stale:
                    del self.cart[pk]
                self.session.modified = True
        return self._products

    def price_for(self, product):
        return product.price_for(self.tier)

    def __iter__(self):
        products = self._load_products()
        for product_id, qty in self.cart.items():
            product = products.get(product_id)
            if product is None:
                continue
            price = self.price_for(product)
            yield {
                'product': product,
                'qty': qty,
                'price': price,
                'total_price': price * qty,
            }

    def __len__(self):
        return sum(int(q) for q in self.cart.values())

    def __bool__(self):
        return bool(self.cart)

    @property
    def is_empty(self):
        return not self.cart

    @property
    def line_count(self):
        return len(self.cart)

    def get_total_price(self):
        return sum((item['total_price'] for item in self), Decimal('0.00'))

    @property
    def total(self):
        return self.get_total_price()

    def quantity_of(self, product_id):
        return int(self.cart.get(str(product_id), 0))

    def summary(self):
        """Compact JSON-friendly snapshot used by the AJAX endpoints."""
        return {
            'qty': len(self),
            'lines': self.line_count,
            'total': float(self.get_total_price()),
            'tier': self.tier,
        }
