"""
Cancel M-Pesa orders that were never paid, so the stock they reserve goes back on sale.

Run from a timer (see deploy/systemd/mahitaji-maintenance.service), e.g. hourly.
Cash-on-delivery orders are never touched: those are confirmed by staff.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Order


class Command(BaseCommand):
    help = "Cancel unpaid M-Pesa orders older than UNPAID_ORDER_EXPIRY_HOURS (default 24)."

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=settings.UNPAID_ORDER_EXPIRY_HOURS)
        parser.add_argument('--dry-run', action='store_true', help="List the orders without cancelling them.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options['hours'])
        stale = Order.objects.filter(
            payment_method=Order.PAYMENT_MPESA, paid_at__isnull=True,
            status__in=(Order.STATUS_PENDING, Order.STATUS_FAILED), created_at__lt=cutoff,
        ).order_by('created_at')
        count = 0
        for order in stale.iterator():
            if order.is_paid:  # belt and braces: a payment may have landed since the query ran
                continue
            self.stdout.write(f"{order.order_number}  placed {order.created_at:%Y-%m-%d %H:%M}  KSh {order.total_amount:,.0f}")
            if not options['dry_run']:
                order.status = Order.STATUS_CANCELLED
                order.save()  # the status-change signal releases the stock
            count += 1
        verb = "would cancel" if options['dry_run'] else "cancelled"
        self.stdout.write(self.style.SUCCESS(f"{verb} {count} unpaid order(s) older than {options['hours']}h"))
