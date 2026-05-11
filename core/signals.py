from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Product, StockLedger, Order, OrderItem

@receiver(post_save, sender=Product)
def init_stock_on_product_creation(sender, instance, created, **kwargs):
    """
    Automatically creates a ledger entry when a new product is added.
    This is vital for Bulk Uploads to initialize stock.
    """
    if created:
        StockLedger.objects.create(
            product=instance,
            transaction_type='PURCHASE',
            quantity=0, # Match your model field name
            reference_number="INITIAL_IMPORT"
        )

@receiver(post_save, sender=Order)
def process_stock_on_payment(sender, instance, **kwargs):
    """
    Detects when an order status changes to 'PAID' and deducts stock.
    """
    if instance.status == 'PAID':
        order_items = instance.items.all()
        for item in order_items:
            # Check if we already recorded this sale to prevent double-deduction
            ref = f"ORDER-{instance.order_number}"
            if not StockLedger.objects.filter(reference_number=ref, product=item.product).exists():
                StockLedger.objects.create(
                    product=item.product,
                    transaction_type='SALE',
                    # Sales are usually done in the base unit (Pieces)
                    transaction_uom=item.product.unit_of_measure, 
                    input_quantity=item.quantity,
                    reference_number=ref
                )