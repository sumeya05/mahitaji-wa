import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .context_processors import invalidate_catalogue_nav, invalidate_price_list
from .models import Brand, Category, Order, Product, StockLedger
from .services import sync_order_stock

# The header/filters navigation and the price list CSV are cached; drop them whenever the
# catalogue changes. Stock entries only affect the price list's "In stock" column.
for _model in (Product, Category, Brand):
    post_save.connect(invalidate_catalogue_nav, sender=_model, dispatch_uid=f'nav-cache-save-{_model.__name__}')
    post_delete.connect(invalidate_catalogue_nav, sender=_model, dispatch_uid=f'nav-cache-delete-{_model.__name__}')
post_save.connect(invalidate_price_list, sender=StockLedger, dispatch_uid='price-list-cache-save-StockLedger')
post_delete.connect(invalidate_price_list, sender=StockLedger, dispatch_uid='price-list-cache-delete-StockLedger')

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
    An order holds its stock from checkout until it is cancelled, so the only status
    changes that move stock are into and out of Cancelled. (A new order has no lines
    yet when it is first saved; checkout books its stock once the lines exist.)
    """
    if created:
        return
    previous = getattr(instance, '_previous_status', None)
    if previous != instance.status and Order.STATUS_CANCELLED in (previous, instance.status):
        sync_order_stock(instance)
