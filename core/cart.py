"""
Session based shopping cart.

The session only stores ``{product_id: quantity}`` and the coupon code. Prices
are always resolved from the product at read time using the customer's price
tier, so a wholesaler who logs in after filling the cart as a guest is charged
wholesale prices, and price changes in the catalogue are always reflected.

Money, top to bottom:

    subtotal   list-price total of the lines at the customer's tier
    discount   the coupon's percentage of the subtotal
    total      subtotal - discount: what the customer pays (VAT included)
    vat        the VAT contained in the total, each line at its product's rate
    net        total - vat
"""
from decimal import Decimal

from django.conf import settings

from .models import PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE, TWO_PLACES, Coupon, Product, vat_included

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
        self._coupon_loaded = False
        self._coupon = None

    # --- mutations ---------------------------------------------------------
    def max_quantity(self, product):
        """Most units of ``product`` one cart may hold: the line cap, or what is left in stock."""
        available = product.available_stock
        return MAX_QTY_PER_LINE if available is None else min(MAX_QTY_PER_LINE, available)

    def add(self, product, quantity=1):
        """Add ``quantity`` units and return how many the cart now holds (it may be fewer
        than asked for when stock runs short)."""
        product_id = str(product.id)
        wanted = self.cart.get(product_id, 0) + max(1, int(quantity))
        return self._set(product_id, min(wanted, self.max_quantity(product)))

    def update(self, product_id, qty):
        """Set a line's quantity (0 removes it) and return the quantity actually kept."""
        product_id = str(product_id)
        qty = int(qty)
        if product_id not in self.cart:
            return 0
        product = self._load_products().get(product_id)
        if product is None:
            return 0
        return self._set(product_id, min(qty, self.max_quantity(product)))

    def _set(self, product_id, qty):
        if qty <= 0:
            self.cart.pop(product_id, None)
            qty = 0
        else:
            self.cart[product_id] = qty
        self._save()
        return qty

    def delete(self, product_id):
        self._set(str(product_id), 0)

    def clear(self):
        """Empty the cart after an order is placed. The coupon goes with it: one code per order."""
        self.session[settings.CART_SESSION_ID] = {}
        self.cart = self.session[settings.CART_SESSION_ID]
        self.set_coupon(None)
        self._save()

    def _save(self):
        self.session.modified = True

    # --- reads -------------------------------------------------------------
    def _load_products(self):
        if self._products is None:
            if not self.cart:
                self._products = {}
                return self._products
            ids = [int(pk) for pk in self.cart.keys() if str(pk).isdigit()]
            products = Product.objects.filter(id__in=ids, is_active=True).with_relations().with_stock()
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
        self._load_products()
        return sum(int(q) for q in self.cart.values())

    def __bool__(self):
        return not self.is_empty

    @property
    def is_empty(self):
        self._load_products()
        return not self.cart

    @property
    def line_count(self):
        self._load_products()
        return len(self.cart)

    def quantity_of(self, product_id):
        return int(self.cart.get(str(product_id), 0))

    def stock_problems(self):
        """Messages for lines that can no longer be supplied in full (checked again at checkout)."""
        problems = []
        for item in self:
            product, available = item['product'], item['product'].available_stock
            if available is None or item['qty'] <= available:
                continue
            if available <= 0:
                problems.append(f"{product.name} is out of stock.")
            else:
                problems.append(f"Only {available} of {product.name} left in stock.")
        return problems

    # --- coupon ------------------------------------------------------------
    @property
    def coupon(self):
        if not self._coupon_loaded:
            code = self.session.get(settings.COUPON_SESSION_ID)
            self._coupon = Coupon.usable(code) if code else None
            if code and self._coupon is None:   # expired or switched off since it was applied
                self.session.pop(settings.COUPON_SESSION_ID, None)
                self.session.modified = True
            self._coupon_loaded = True
        return self._coupon

    def set_coupon(self, coupon):
        if coupon is None:
            self.session.pop(settings.COUPON_SESSION_ID, None)
        else:
            self.session[settings.COUPON_SESSION_ID] = coupon.code
        self.session.modified = True
        self._coupon, self._coupon_loaded = coupon, True

    # --- money -------------------------------------------------------------
    def get_total_price(self):
        """List-price total of the lines, before the coupon."""
        return sum((item['total_price'] for item in self), Decimal('0.00'))

    @property
    def subtotal(self):
        return self.get_total_price()

    @property
    def discount_percent(self):
        return self.coupon.percent if self.coupon else Decimal('0')

    @property
    def discount(self):
        return (self.subtotal * self.discount_percent / 100).quantize(TWO_PLACES)

    @property
    def total(self):
        """What the customer pays: the subtotal less the coupon, VAT included."""
        return self.subtotal - self.discount

    @property
    def vat(self):
        """VAT contained in the total. The coupon lowers every line by the same share, so it lowers the VAT too."""
        vat = sum((vat_included(item['total_price'], item['product'].vat_rate) for item in self), Decimal('0'))
        return (vat * (100 - self.discount_percent) / 100).quantize(TWO_PLACES)

    @property
    def net(self):
        return self.total - self.vat

    def summary(self):
        """Compact JSON-friendly snapshot used by the AJAX endpoints."""
        return {
            'qty': len(self),
            'lines': self.line_count,
            'subtotal': float(self.subtotal),
            'discount': float(self.discount),
            'vat': float(self.vat),
            'net': float(self.net),
            'total': float(self.total),
            'coupon': self.coupon.code if self.coupon else '',
            'tier': self.tier,
        }
