import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .context_processors import invalidate_catalogue_nav
from .models import Brand, Category, Order, Product, StockLedger

# The header/filters navigation is cached; drop it whenever the catalogue changes.
for _model in (Product, Category, Brand):
    post_save.connect(invalidate_catalogue_nav, sender=_model, dispatch_uid=f'nav-cache-save-{_model.__name__}')
    post_delete.connect(invalidate_catalogue_nav, sender=_model, dispatch_uid=f'nav-cache-delete-{_model.__name__}')

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Product)
def init_stock_on_product_creation(sender, instance, created, **kwargs):
    """Create an opening ledger entry so bulk-imported products start at a known stock level."""
    if created and not instance.stock_ledger.exists():
        StockLedger.objects.create(
            product=instance,
            transaction_type='PURCHASE',
            quantity=0,
            reference_number="INITIAL_IMPORT",
        )


@receiver(pre_save, sender=Order)
def remember_previous_status(sender, instance, **kwargs):
    """Stash the previous status so post_save can react only to real transitions."""
    if instance.pk:
        instance._previous_status = (
            Order.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
        )
    else:
        instance._previous_status = None


@receiver(post_save, sender=Order)
def adjust_stock_on_status_change(sender, instance, created, **kwargs):
    """
    Deduct stock once an order is paid, shipped or delivered (cash-on-delivery orders
    skip "paid"), and put it back if such an order is cancelled.
    Ledger references make both operations idempotent.
    """
    previous = getattr(instance, '_previous_status', None)
    if previous == instance.status:
        return

    sale_ref = f"ORDER-{instance.order_number}"
    restock_ref = f"RESTOCK-{instance.order_number}"

    fulfilled = (Order.STATUS_PAID, Order.STATUS_SHIPPED, Order.STATUS_DELIVERED)

    if instance.status in fulfilled:
        for item in instance.items.select_related('product'):
            if not StockLedger.objects.filter(reference_number=sale_ref, product=item.product).exists():
                StockLedger.objects.create(
                    product=item.product,
                    transaction_type='SALE',
                    quantity=-abs(item.quantity),
                    reference_number=sale_ref,
                )
    elif instance.status == Order.STATUS_CANCELLED and previous in fulfilled:
        for item in instance.items.select_related('product'):
            sold = StockLedger.objects.filter(reference_number=sale_ref, product=item.product).exists()
            restocked = StockLedger.objects.filter(reference_number=restock_ref, product=item.product).exists()
            if sold and not restocked:
                StockLedger.objects.create(
                    product=item.product,
                    transaction_type='ADJUSTMENT',
                    quantity=abs(item.quantity),
                    reference_number=restock_ref,
                )
