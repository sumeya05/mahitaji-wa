"""
Fill the new order fields for orders placed before they existed:

* ``paid_at``      orders already Paid, orders with a successful M-Pesa payment, and
                   delivered cash-on-delivery orders (the driver collected the money)
* ``vat_amount``   the VAT contained in the total, each line at its product's rate
* ``result_code``  0 on M-Pesa attempts that had succeeded
"""
from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    Order = apps.get_model('core', 'Order')
    MpesaTransaction = apps.get_model('core', 'MpesaTransaction')

    MpesaTransaction.objects.filter(is_success=True, result_code__isnull=True).update(result_code=0)

    for order in Order.objects.prefetch_related('items__product', 'mpesa_payments'):
        changed = []
        if order.paid_at is None:
            success = next((t for t in order.mpesa_payments.all() if t.is_success), None)
            delivered_cod = order.status == 'DELIVERED' and order.payment_method == 'cod'
            shipped_mpesa = order.status in ('SHIPPED', 'DELIVERED') and order.payment_method == 'mpesa'
            if success or order.status == 'PAID' or delivered_cod or shipped_mpesa:
                order.paid_at = (success.transaction_date if success and success.transaction_date else None) or order.updated_at
                changed.append('paid_at')
        if not order.vat_amount:
            vat = sum(
                (item.price_at_purchase * item.quantity * item.product.vat_rate / (100 + item.product.vat_rate)
                 for item in order.items.all()),
                Decimal('0'),
            )
            order.vat_amount = vat.quantize(Decimal('0.01'))
            changed.append('vat_amount')
        if changed:
            # queryset.update keeps ``updated_at`` (auto_now) untouched
            Order.objects.filter(pk=order.pk).update(**{name: getattr(order, name) for name in changed})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_coupons_vat_stock_payments'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
