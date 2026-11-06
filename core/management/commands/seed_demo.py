"""
Fill an empty development database with a small sample shop, for previewing the website or
the mobile app locally: five categories, a dozen products from brands Mahitaji stocks (using
the brand logos and category pictures in static/assets/), stock, the KARIBU5 coupon and a
retail customer, amina@example.com / Duka2026!secure.

    DEBUG=true USE_SQLITE=true python manage.py seed_demo

It refuses to run with DEBUG off or when the catalogue already has products, so it can never
put sample data into the real shop.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    Address, Brand, Category, Coupon, CustomerProfile, Product, StockLedger, UnitOfMeasure,
)

ASSETS = settings.BASE_DIR / 'static' / 'assets'

CATEGORIES = [
    ('Cereals & Flour', 'flour.jpg'), ('Cooking Oils', 'oils.jpg'), ('Beverages', 'drinks.jpg'),
    ('Soaps & Detergents', 'soaps.jpg'), ('Rice & Grains', 'cereals.jpg'),
]
BRANDS = [
    ('Ajab', 'ajab.jpeg'), ('Soko', 'soko.jpeg'), ('Kapa Oil', 'kapa.png'), ('Ketepa', 'ketepa.jpeg'),
    ('Coca-Cola', 'cocacola.png'), ('Del Monte', 'delmonte.png'), ('Pembe', 'pembe.jpeg'),
    ('Kensalt', 'kensalt.jpeg'), ('Tropical Heat', 'tropicalheat.jpeg'), ('Jetlak', 'jetlak.png'), ('EXE', 'exe.png'),
]
# name, item code, category, brand, unit, retail, wholesale, old retail, old wholesale, best seller, trending, stock
PRODUCTS = [
    ('Ajab Home Baking Flour 2kg x 12', 'AJ001', 'Cereals & Flour', 'Ajab', 'Bale', '2040', '1980', '2150', None, True, False, 120),
    ('Soko Maize Meal 2kg x 12', 'SK001', 'Cereals & Flour', 'Soko', 'Bale', '1740', '1690', None, None, True, True, 120),
    ('Kapa Cooking Oil 3L x 4', 'KP001', 'Cooking Oils', 'Kapa Oil', 'Carton', '2280', '2210', '2390', '2290', False, True, 120),
    ('Kapa Cooking Oil 1L x 12', 'KP002', 'Cooking Oils', 'Kapa Oil', 'Carton', '2460', '2390', None, None, True, False, 120),
    ('Ketepa Pride Tea Bags 100s x 12', 'KT001', 'Beverages', 'Ketepa', 'Carton', '3120', '3020', '3300', None, True, True, 3),
    ('Coca-Cola 500ml x 24', 'CC001', 'Beverages', 'Coca-Cola', 'Carton', '1560', '1490', None, None, False, True, 120),
    ('Del Monte Mango Juice 1L x 12', 'DM001', 'Beverages', 'Del Monte', 'Carton', '2880', '2790', '3050', '2950', False, False, 120),
    ('Pembe Maize Flour 2kg x 12', 'PB001', 'Cereals & Flour', 'Pembe', 'Bale', '1710', '1660', None, None, False, False, 120),
    ('Kensalt Table Salt 1kg x 20', 'KS001', 'Rice & Grains', 'Kensalt', 'Bale', '1180', '1140', None, None, False, False, 120),
    ('Tropical Heat Royco Mix 200g x 24', 'TH001', 'Rice & Grains', 'Tropical Heat', 'Carton', '2650', None, '2790', None, False, True, 120),
    ('Jetlak Bar Soap 800g x 20', 'JL001', 'Soaps & Detergents', 'Jetlak', 'Carton', '3380', '3290', None, None, True, False, 120),
    ('EXE Washing Powder 1kg x 12', 'EX001', 'Soaps & Detergents', 'EXE', 'Carton', '2160', '2090', None, None, False, False, 120),
]


def money(value):
    return Decimal(value) if value else None


class Command(BaseCommand):
    help = "Fill an empty development database with a sample shop for local previews (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=true: it must never touch the real shop.")
        if Product.objects.exists():
            raise CommandError("The catalogue already has products; seed_demo only fills an empty database.")

        with transaction.atomic():
            categories = {}
            for name, picture in CATEGORIES:
                category = Category.objects.create(name=name)
                with open(ASSETS / 'categories' / picture, 'rb') as f:
                    category.image.save(picture, File(f))
                categories[name] = category
            brands = {}
            for name, logo in BRANDS:
                brand, _ = Brand.objects.get_or_create(name=name)
                with open(ASSETS / 'brands' / logo, 'rb') as f:
                    brand.logo.save(logo, File(f))
                brands[name] = brand
            units = {
                'Carton': UnitOfMeasure.objects.get_or_create(name='Carton', defaults={'short_name': 'ctn'})[0],
                'Bale': UnitOfMeasure.objects.get_or_create(name='Bale', defaults={'short_name': 'bl'})[0],
            }
            for (name, code, category, brand, unit, retail, wholesale, old_retail, old_wholesale,
                 best_seller, trending, stock) in PRODUCTS:
                product = Product.objects.create(
                    name=name, item_code=code, category=categories[category], brand=brands[brand],
                    unit_of_measure=units[unit], retail_price=money(retail), wholesale_price=money(wholesale),
                    old_retail_price=money(old_retail), old_wholesale_price=money(old_wholesale),
                    is_best_seller=best_seller, is_trending=trending,
                    description=f"Sample catalogue entry. Sold by the {unit.lower()}.",
                )
                StockLedger.objects.create(product=product, transaction_type='PURCHASE', quantity=stock,
                                           reference_number='SAMPLE')

            Coupon.objects.get_or_create(code='KARIBU5', defaults={'percent': Decimal('5'), 'promote': True})
            if not User.objects.filter(email__iexact='amina@example.com').exists():
                user = User.objects.create_user('amina-duka', email='amina@example.com', password='Duka2026!secure',
                                                first_name='Amina', last_name='Wanjiru')
                profile = CustomerProfile.objects.create(user=user, phone_number='254712345678',
                                                         business_name='Amina Mini Mart')
                Address.objects.create(customer=profile, label='Main shop', physical_address='Gikomba Market, stall 14',
                                       city='Nairobi', is_primary=True)

        self.stdout.write(self.style.SUCCESS(
            f"Sample shop ready: {len(PRODUCTS)} products. Sign in as amina@example.com / Duka2026!secure, coupon KARIBU5."))
