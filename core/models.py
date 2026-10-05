import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Exists, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


PRICE_TIER_RETAIL = 'retail'
PRICE_TIER_WHOLESALE = 'wholesale'

# Kenya's standard VAT rate. Catalogue prices include VAT; zero-rated and exempt lines carry 0.
DEFAULT_VAT_RATE = Decimal('16')
TWO_PLACES = Decimal('0.01')


def vat_included(amount, rate):
    """The VAT contained in a VAT-inclusive ``amount`` at ``rate`` percent."""
    rate = Decimal(rate or 0)
    return Decimal(amount) * rate / (100 + rate)


def plain_number(value):
    """A decimal without trailing zeros: 16.00 -> "16", 7.50 -> "7.5" (for "16%" style labels)."""
    return format(Decimal(value).normalize(), 'f')


def bounded_slug(text, max_length, fallback='item'):
    """A slug cut to fit its column (MySQL rejects longer values instead of truncating them)."""
    return (slugify(text)[:max_length].strip('-')) or fallback


# ---------------------------------------------------------------------------
# A. Customers
# ---------------------------------------------------------------------------
class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customerprofile')
    business_name = models.CharField(max_length=255, blank=True, null=True)
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    tax_id = models.CharField(max_length=15, null=True, blank=True, verbose_name="KRA PIN")
    is_wholesaler = models.BooleanField(default=False)
    erp_id = models.CharField(max_length=50, null=True, blank=True, verbose_name='ERP customer ID')

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f"{self.display_name} ({self.tier_label})"

    @property
    def display_name(self):
        return self.business_name or self.user.get_full_name() or self.user.username

    @property
    def price_tier(self):
        return PRICE_TIER_WHOLESALE if self.is_wholesaler else PRICE_TIER_RETAIL

    @property
    def tier_label(self):
        return "Wholesaler" if self.is_wholesaler else "Retailer"

    @property
    def primary_address(self):
        return self.addresses.filter(is_primary=True).first() or self.addresses.first()


class Address(models.Model):
    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=50, default="Delivery Address")
    physical_address = models.TextField()
    city = models.CharField(max_length=100, default="Nairobi")
    is_primary = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Addresses"
        ordering = ['-is_primary', 'id']

    def __str__(self):
        return f"{self.label} - {self.customer.user.username}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Only one primary address per customer.
        if self.is_primary:
            Address.objects.filter(customer=self.customer, is_primary=True).exclude(pk=self.pk).update(is_primary=False)


# ---------------------------------------------------------------------------
# B. Catalogue
# ---------------------------------------------------------------------------
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = bounded_slug(self.name, self._meta.get_field('slug').max_length)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return f"{reverse('products')}?category={self.slug}"

    @property
    def image_url(self):
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        return None


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = bounded_slug(self.name, self._meta.get_field('slug').max_length)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return f"{reverse('products')}?brand={self.slug}"

    @property
    def logo_url(self):
        if self.logo and hasattr(self.logo, 'url'):
            return self.logo.url
        return None


class Supplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    erp_id = models.CharField(max_length=50, blank=True, null=True, help_text="Supplier ID in Focus ERP")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UnitOfMeasure(models.Model):
    name = models.CharField(max_length=50, unique=True)          # e.g. "Bale", "Piece"
    short_name = models.CharField(max_length=10, unique=True)    # e.g. "bl", "pc"
    is_base_unit = models.BooleanField(default=False, help_text="Is this the smallest unit (e.g., Piece)?")
    base_unit = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversions')
    conversion_factor = models.DecimalField(
        max_digits=10, decimal_places=2, default=1.0,
        help_text="How many base units are in this unit? (e.g., 1 Bale = 12 Pieces)")

    class Meta:
        verbose_name = "Unit of Measure"
        verbose_name_plural = "Units of Measure"
        ordering = ['name']

    def __str__(self):
        return self.short_name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_relations(self):
        return self.select_related('brand', 'category', 'unit_of_measure')

    def on_offer(self, tier=None):
        """Products with a genuine reduction for ``tier`` (retail / wholesale), or for either when omitted."""
        retail = models.Q(old_retail_price__isnull=False, old_retail_price__gt=models.F('retail_price'))
        wholesale = models.Q(
            wholesale_price__isnull=False, old_wholesale_price__isnull=False,
            old_wholesale_price__gt=models.F('wholesale_price'),
        )
        if tier == PRICE_TIER_WHOLESALE:
            # A wholesaler pays the retail price for lines without a wholesale price, so a
            # retail reduction on such a line is a real offer for them too.
            return self.filter(wholesale | (models.Q(wholesale_price__isnull=True) & retail))
        if tier == PRICE_TIER_RETAIL:
            return self.filter(retail)
        return self.filter(retail | wholesale)

    def with_wholesale_price(self):
        return self.filter(wholesale_price__isnull=False)

    def with_stock(self):
        """Pre-compute the stock figures ``Product.stock_state`` needs, so a page of
        products costs no extra query per product."""
        ledger = StockLedger.objects.filter(product=OuterRef('pk'))
        total = ledger.order_by().values('product').annotate(total=Sum('quantity')).values('total')
        return self.annotate(
            stock_total=Coalesce(Subquery(total, output_field=models.IntegerField()), 0),
            stock_tracked=Exists(ledger.filter(quantity__gt=0)),
        )


class Product(models.Model):
    item_code = models.CharField(max_length=50, unique=True, null=True, help_text="Focus ERP item code")
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    old_retail_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_column='old_price',
        help_text="Previous retail price; when higher than the retail price the product is a retail offer.",
    )
    retail_price = models.DecimalField(default=100, max_digits=12, decimal_places=2, null=True, blank=True)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    old_wholesale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Previous wholesale price; when higher than the wholesale price the product is a wholesale offer.",
    )
    vat_rate = models.DecimalField(
        'VAT rate (%)', max_digits=5, decimal_places=2, default=DEFAULT_VAT_RATE, db_default=DEFAULT_VAT_RATE,
        help_text="VAT included in the prices above: 16 for standard-rated goods, 0 for zero-rated or exempt lines.",
    )
    average_rating = models.PositiveIntegerField(default=4)
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    last_sync_time = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_trending = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.item_code} - {self.name}"

    def get_absolute_url(self):
        return reverse('product_detail', args=[self.pk])

    # --- pricing -----------------------------------------------------------
    def price_for(self, tier=PRICE_TIER_RETAIL):
        """Price for a given tier, always falling back to a usable number."""
        if tier == PRICE_TIER_WHOLESALE and self.wholesale_price is not None:
            return self.wholesale_price
        if self.retail_price is not None:
            return self.retail_price
        return self.wholesale_price if self.wholesale_price is not None else Decimal('0.00')

    def tier_used(self, tier=PRICE_TIER_RETAIL):
        """The tier ``price_for`` actually applied (wholesale falls back to retail when unset)."""
        if tier == PRICE_TIER_WHOLESALE and self.wholesale_price is not None:
            return PRICE_TIER_WHOLESALE
        return PRICE_TIER_RETAIL

    def old_price_for(self, tier=PRICE_TIER_RETAIL):
        """The previous price for the tier that is really being charged, if it was higher."""
        if self.tier_used(tier) == PRICE_TIER_WHOLESALE:
            old, now = self.old_wholesale_price, self.wholesale_price
        else:
            old, now = self.old_retail_price, self.retail_price
        if old is not None and now is not None and old > now:
            return old
        return None

    def has_discount_for(self, tier=PRICE_TIER_RETAIL):
        return self.old_price_for(tier) is not None

    def discount_percentage_for(self, tier=PRICE_TIER_RETAIL):
        """Whole-number percentage string (e.g. '12%') or None when there is no real discount."""
        old = self.old_price_for(tier)
        if old is None:
            return None
        discount = ((old - self.price_for(tier)) / old) * 100
        return f"{max(int(discount), 1)}%"

    def amount_saved_for(self, tier=PRICE_TIER_RETAIL):
        old = self.old_price_for(tier)
        return old - self.price_for(tier) if old is not None else Decimal('0.00')

    # Retail shorthands (admin, API, legacy templates).
    @property
    def has_discount(self):
        return self.has_discount_for(PRICE_TIER_RETAIL)

    @property
    def discount_percentage(self):
        return self.discount_percentage_for(PRICE_TIER_RETAIL)

    @property
    def amount_saved(self):
        return self.amount_saved_for(PRICE_TIER_RETAIL)

    @property
    def is_purchasable(self):
        """A product with no price set must never be sold for KSh 0."""
        return self.price_for(PRICE_TIER_RETAIL) > 0

    # --- stock -------------------------------------------------------------
    # The ledger counts this product's own unit of sale (cartons for a carton line).
    # Querysets built with ``.with_stock()`` carry ``stock_total`` / ``stock_tracked``
    # so none of these properties runs a query per product.
    @property
    def current_stock(self):
        if hasattr(self, 'stock_total'):
            return self.stock_total or 0
        total = self.stock_ledger.aggregate(total=Sum('quantity'))['total']
        return total or 0

    @property
    def is_stock_tracked(self):
        """The ledger only speaks for a product once stock has actually been received for it;
        until then the product stays available to order."""
        if hasattr(self, 'stock_tracked'):
            return bool(self.stock_tracked)
        return self.stock_ledger.filter(quantity__gt=0).exists()

    @property
    def available_stock(self):
        """Units that can still be ordered, or None while stock is not tracked."""
        return max(self.current_stock, 0) if self.is_stock_tracked else None

    @property
    def stock_state(self):
        """'in', 'low' or 'out'; '' while stock is not tracked (then nothing is blocked)."""
        available = self.available_stock
        if available is None:
            return ''
        if available <= 0:
            return 'out'
        return 'low' if available <= settings.LOW_STOCK_THRESHOLD else 'in'

    @property
    def in_stock(self):
        return self.stock_state != 'out'

    def get_stock_state_display(self):
        return {'in': 'In stock', 'low': 'Low stock', 'out': 'Out of stock'}.get(self.stock_state, 'Not tracked')

    # --- presentation ------------------------------------------------------
    @property
    def image_url(self):
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        return f"{settings.STATIC_URL}assets/images/placeholder.svg"

    @property
    def has_image(self):
        return bool(self.image)

    @property
    def initials(self):
        words = [w for w in self.name.replace('-', ' ').split() if w.isalpha()]
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        return self.name[:2].upper()

    @property
    def placeholder_hue(self):
        seed = (self.category.name if self.category else self.name)
        return sum(ord(c) for c in seed) % 360

    @property
    def pack_size(self):
        """Full unit name for display ("Carton", "Dozen"), normalised because the
        catalogue import left names in mixed case."""
        if not self.unit_of_measure:
            return ''
        return self.unit_of_measure.name.strip().title()

    def save(self, *args, **kwargs):
        max_length = self._meta.get_field('slug').max_length
        if not self.slug:
            self.slug = bounded_slug(self.name, max_length, 'product')
        base_slug = self.slug
        counter = 1
        while Product.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
            suffix = f"-{counter:03d}"
            self.slug = base_slug[:max_length - len(suffix)].rstrip('-') + suffix
            counter += 1
        super().save(*args, **kwargs)


class StockLedger(models.Model):
    TRANSACTION_TYPES = [
        ('PURCHASE', 'Stock In'),
        ('SALE', 'Stock Out'),
        ('ADJUSTMENT', 'Adjustment'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_ledger')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField(help_text="Quantity in the product's own unit of sale (positive for stock in, negative for stock out)")
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Stock Ledger"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.product.item_code} | {self.transaction_type} | {self.quantity}"


# ---------------------------------------------------------------------------
# C. Orders
# ---------------------------------------------------------------------------
class Order(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_PAID = 'PAID'
    STATUS_FAILED = 'FAILED'
    STATUS_SHIPPED = 'SHIPPED'
    STATUS_DELIVERED = 'DELIVERED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    )
    PAYMENT_COD = 'cod'
    PAYMENT_MPESA = 'mpesa'
    PAYMENT_CHOICES = (
        (PAYMENT_COD, 'Cash on Delivery'),
        (PAYMENT_MPESA, 'M-Pesa'),
    )

    customer = models.ForeignKey(CustomerProfile, on_delete=models.SET_NULL, null=True, related_name='orders')
    order_number = models.CharField(max_length=20, unique=True)

    # Snapshot of the delivery details at the time of ordering.
    full_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, default="Nairobi")
    notes = models.TextField(blank=True, null=True)

    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default=PAYMENT_COD)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text='What the customer pays: after any coupon, VAT included')
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0, help_text='VAT included in the total')
    coupon_code = models.CharField(max_length=30, blank=True, default='', db_default='')
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, db_default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0, help_text='Already taken off the total')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    paid_at = models.DateTimeField(null=True, blank=True, help_text='When payment was received; empty while the order is unpaid')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    synced_to_erp = models.BooleanField(default=False)
    erp_reference = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order {self.order_number}"

    @classmethod
    def generate_order_number(cls):
        while True:
            candidate = f"MAH-{uuid.uuid4().hex[:8].upper()}"
            if not cls.objects.filter(order_number=candidate).exists():
                return candidate

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        # Marking an order Paid, or delivering a cash-on-delivery order (the driver collects
        # the money), is when payment is received.
        collected = self.status == self.STATUS_PAID or (
            self.status == self.STATUS_DELIVERED and self.payment_method == self.PAYMENT_COD)
        if collected and self.paid_at is None:
            self.paid_at = timezone.now()
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'paid_at'}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('order_detail', args=[self.order_number])

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    # --- money -------------------------------------------------------------
    @property
    def subtotal_amount(self):
        """List-price total of the items, before the coupon."""
        return self.total_amount + self.discount_amount

    @property
    def net_amount(self):
        return self.total_amount - self.vat_amount

    @property
    def is_paid(self):
        return self.paid_at is not None

    @property
    def needs_refund(self):
        return self.is_paid and self.status == self.STATUS_CANCELLED

    def mark_paid(self, when=None):
        """Record a received payment. A pending or failed order moves on to Paid; an order
        that was cancelled in the meantime stays cancelled (and now needs a refund)."""
        self.paid_at = self.paid_at or when or timezone.now()
        if self.status in (self.STATUS_PENDING, self.STATUS_FAILED):
            self.status = self.STATUS_PAID
        self.save()

    @property
    def latest_payment(self):
        """The M-Pesa attempt that matters: the successful one if there is one, else the newest."""
        attempts = list(self.mpesa_payments.all())
        return next((txn for txn in attempts if txn.is_success), attempts[0] if attempts else None)

    @property
    def can_pay(self):
        return (not self.is_paid and self.payment_method == self.PAYMENT_MPESA
                and self.status in (self.STATUS_PENDING, self.STATUS_FAILED))

    @property
    def can_cancel(self):
        return not self.is_paid and self.status in (self.STATUS_PENDING, self.STATUS_FAILED)

    @property
    def status_tone(self):
        return {
            self.STATUS_PENDING: 'warning',
            self.STATUS_PAID: 'success',
            self.STATUS_SHIPPED: 'info',
            self.STATUS_DELIVERED: 'success',
            self.STATUS_FAILED: 'danger',
            self.STATUS_CANCELLED: 'muted',
        }.get(self.status, 'muted')

    @property
    def progress_step(self):
        """0..3 used by the order timeline: placed, paid, shipped, delivered."""
        return {
            self.STATUS_PENDING: 0,
            self.STATUS_FAILED: 0,
            self.STATUS_CANCELLED: 0,
            self.STATUS_PAID: 1,
            self.STATUS_SHIPPED: 2,
            self.STATUS_DELIVERED: 3,
        }.get(self.status, 0)


class Coupon(models.Model):
    """Percentage discount on the whole order, typed in at the cart or checkout."""
    code = models.CharField(max_length=30, unique=True, help_text='What customers type, e.g. KARIBU5 (not case-sensitive)')
    percent = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('100'))],
        help_text='Discount on the order total, e.g. 5',
    )
    active = models.BooleanField(default=True)
    valid_until = models.DateField(null=True, blank=True, help_text='Last day it can be used; empty = no end date')
    promote = models.BooleanField(default=False, help_text='Advertise this code in the offer pop-up on the site')

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} ({plain_number(self.percent)}%)'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @classmethod
    def usable(cls, code):
        """The active, unexpired coupon with this code, or None."""
        code = (code or '').strip()
        if not code:
            return None
        return cls.objects.filter(code__iexact=code, active=True).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.localdate())).first()


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    @property
    def subtotal(self):
        if self.price_at_purchase is None or self.quantity is None:
            return Decimal('0.00')
        return self.price_at_purchase * self.quantity

    line_total = subtotal


# ---------------------------------------------------------------------------
# D. Payments (M-Pesa)
# ---------------------------------------------------------------------------
class MpesaTransaction(models.Model):
    """One STK push. An order keeps every attempt, so a customer who asks for a second
    prompt and then approves the first one is still matched to their payment."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='mpesa_payments')
    checkout_request_id = models.CharField(max_length=100, unique=True)
    merchant_request_id = models.CharField(max_length=100)
    receipt_number = models.CharField(max_length=50, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15)
    transaction_date = models.DateTimeField(null=True, blank=True)
    is_success = models.BooleanField(default=False)
    result_code = models.IntegerField(null=True, blank=True, help_text='Outcome reported by Safaricom: 0 = paid, empty = no outcome yet')
    response_description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"M-Pesa {self.receipt_number or self.checkout_request_id}"

    @property
    def state(self):
        """'paid', 'failed' or 'pending' (no outcome from Safaricom yet)."""
        if self.is_success:
            return 'paid'
        return 'pending' if self.result_code is None else 'failed'


# ---------------------------------------------------------------------------
# E. Engagement
# ---------------------------------------------------------------------------
class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} ♥ {self.product.name}"


class ContactMessage(models.Model):
    INQUIRY_CHOICES = (
        ('order', 'Order Status / Delivery'),
        ('partnership', 'Manufacturer Partnership'),
        ('feedback', 'General Feedback'),
        ('registration', 'Registration'),
        ('other', 'Other'),
    )
    full_name = models.CharField(max_length=150)
    business_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    inquiry_type = models.CharField(max_length=20, choices=INQUIRY_CHOICES, default='other')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name} - {self.get_inquiry_type_display()}"


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email


# ---------------------------------------------------------------------------
# G. Assistant chat log
# ---------------------------------------------------------------------------
class ChatMessage(models.Model):
    """One question/answer exchange with the shopping assistant, kept so the
    questions customers actually ask can be reviewed and turned into better
    answers (or FAQ entries) over time."""
    HANDLED_CHOICES = (
        ('order', 'Order status'),
        ('catalogue', 'Catalogue lookup'),
        ('faq', 'FAQ'),
        ('llm', 'Language model'),
        ('fallback', 'Fallback'),
    )

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    message = models.TextField()
    reply = models.TextField()
    handled_by = models.CharField(max_length=12, choices=HANDLED_CHOICES, default='llm', db_index=True)
    product_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} · {self.handled_by} · {self.message[:40]}"
