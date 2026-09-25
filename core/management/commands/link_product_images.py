"""
Attach image files sitting in MEDIA_ROOT/products/ to products that have no image.

Matching is by filename tokens against the product name and brand, so
``golden_fry_3l.jpg`` will be attached to "GOLDEN FRY COOKING OIL 3L".

    python manage.py link_product_images            # dry run, prints matches
    python manage.py link_product_images --apply    # write the matches
"""
import os
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import Product

IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')


def tokens(text):
    text = re.sub(r'_[A-Za-z0-9]{7}(?=\.)', '', text)  # strip Django's random suffixes
    return {t for t in re.split(r'[^a-z0-9]+', text.lower()) if len(t) > 1}


class Command(BaseCommand):
    help = "Link loose files in media/products to products without images (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Actually save the matches.")
        parser.add_argument('--min-score', type=int, default=2, help="Minimum matching tokens (default 2).")

    def handle(self, *args, **options):
        folder = os.path.join(settings.MEDIA_ROOT, 'products')
        if not os.path.isdir(folder):
            self.stdout.write(self.style.WARNING(f"No folder at {folder}"))
            return
        files = [f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXT)]
        products = list(Product.objects.filter(image='').select_related('brand'))
        matched = 0
        for product in products:
            name_tokens = tokens(product.name) | (tokens(product.brand.name) if product.brand else set())
            best, best_score = None, 0
            for filename in files:
                score = len(tokens(os.path.splitext(filename)[0]) & name_tokens)
                if score > best_score:
                    best, best_score = filename, score
            if best and best_score >= options['min_score']:
                matched += 1
                self.stdout.write(f"{product.item_code:<14} {product.name[:45]:<45} -> {best}  (score {best_score})")
                if options['apply']:
                    product.image.name = f"products/{best}"
                    product.save(update_fields=['image'])
        verb = "Linked" if options['apply'] else "Would link"
        self.stdout.write(self.style.SUCCESS(f"{verb} {matched} of {len(products)} image-less products."))
        if not options['apply'] and matched:
            self.stdout.write("Re-run with --apply to save.")
