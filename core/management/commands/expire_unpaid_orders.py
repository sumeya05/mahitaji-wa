"""
Cancel orders that reserve stock but are going nowhere, so the stock goes back on sale:

* M-Pesa orders never paid within UNPAID_ORDER_EXPIRY_HOURS;
* cash-on-delivery orders staff have not confirmed (moved past Pending, e.g. to Paid or
  Shipped in the admin) within UNCONFIRMED_COD_ORDER_EXPIRY_HOURS. Set that to 0 to leave
  cash orders alone.

Run from a timer (see deploy/systemd/mahitaji-maintenance.service), e.g. hourly.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Order


class Command(BaseCommand):
    help = ("Cancel unpaid M-Pesa orders older than UNPAID_ORDER_EXPIRY_HOURS (default 24) and "
            "unconfirmed cash-on-delivery orders older than UNCONFIRMED_COD_ORDER_EXPIRY_HOURS (default 72).")

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=settings.UNPAID_ORDER_EXPIRY_HOURS,
                            help="Age in hours after which an unpaid M-Pesa order is cancelled.")
        parser.add_argument('--cod-hours', type=int, default=settings.UNCONFIRMED_COD_ORDER_EXPIRY_HOURS,
                            help="Age in hours after which a still-Pending cash-on-delivery order is cancelled (0: never).")
        parser.add_argument('--dry-run', action='store_true', help="List the orders without cancelling them.")

    def handle(self, *args, **options):
        unpaid = Order.objects.filter(
            payment_method=Order.PAYMENT_MPESA, paid_at__isnull=True,
            status__in=(Order.STATUS_PENDING, Order.STATUS_FAILED),
            created_at__lt=timezone.now() - timedelta(hours=options['hours']),
        )
        self._cancel(unpaid, "unpaid M-Pesa", options['hours'], options['dry_run'])
        if options['cod_hours'] > 0:
            unconfirmed = Order.objects.filter(
                payment_method=Order.PAYMENT_COD, paid_at__isnull=True, status=Order.STATUS_PENDING,
                created_at__lt=timezone.now() - timedelta(hours=options['cod_hours']),
            )
            self._cancel(unconfirmed, "unconfirmed cash-on-delivery", options['cod_hours'], options['dry_run'])

    def _cancel(self, queryset, label, hours, dry_run):
        count = 0
        for order in queryset.order_by('created_at').iterator():
            if order.is_paid:  # belt and braces: a payment may have landed since the query ran
                continue
            self.stdout.write(f"{order.order_number}  placed {order.created_at:%Y-%m-%d %H:%M}  KSh {order.total_amount:,.0f}")
            if not dry_run:
                order.status = Order.STATUS_CANCELLED
                order.save()  # the status-change signal releases the stock
            count += 1
        verb = "would cancel" if dry_run else "cancelled"
        self.stdout.write(self.style.SUCCESS(f"{verb} {count} {label} order(s) older than {hours}h"))
        return count
