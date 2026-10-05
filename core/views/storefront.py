"""
Public catalogue: home page, product listings (catalogue / retailers / wholesalers / offers), search, categories, brands and the product page.
"""
import csv
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from ..cart import Cart, price_tier_for
from ..context_processors import PRICE_LIST_CACHE_KEY
from ..models import (
    PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE, Brand, Category, Product, plain_number,
)
from ._common import is_ajax, json_ok

logger = logging.getLogger(__name__)


PAGE_SIZE = 24
SORT_OPTIONS = [
    ('featured', 'Featured'),
    ('name', 'Name A–Z'),
    ('price_asc', 'Price: low to high'),
    ('price_desc', 'Price: high to low'),
    ('discount', 'Biggest discount'),
    ('newest', 'Newest'),
]


def _apply_sort(queryset, sort, tier):
    # The price a customer is shown: wholesale falls back to retail when a line has no
    # wholesale price (and the other way round), exactly as Product.price_for does.
    if tier == PRICE_TIER_WHOLESALE:
        price = Coalesce('wholesale_price', 'retail_price')
    else:
        price = Coalesce('retail_price', 'wholesale_price')
    if sort == 'name':
        return queryset.order_by('name')
    if sort == 'price_asc':
        return queryset.annotate(shown_price=price).order_by(F('shown_price').asc(nulls_last=True), 'name')
    if sort == 'price_desc':
        return queryset.annotate(shown_price=price).order_by(F('shown_price').desc(nulls_last=True), 'name')
    if sort == 'newest':
        return queryset.order_by('-created_at', 'name')
    if sort == 'discount':
        price_field = 'wholesale_price' if tier == PRICE_TIER_WHOLESALE else 'retail_price'
        old_field = 'old_wholesale_price' if tier == PRICE_TIER_WHOLESALE else 'old_retail_price'
        return queryset.annotate(discount_amount=F(old_field) - F(price_field)) \
            .order_by(F('discount_amount').desc(nulls_last=True), 'name')
    return queryset.order_by('-is_best_seller', '-is_trending', 'name')


def catalog(request, base_qs, *, title, subtitle='', tier=None, template='core/catalog.html',
            default_sort='featured', extra=None, show_hero=True):
    """Shared listing logic for every product grid page (filters, sort, search, pagination, AJAX)."""
    tier = tier or price_tier_for(request.user)
    q = (request.GET.get('q') or '').strip()
    selected_categories = [s for s in request.GET.getlist('category') if s]
    selected_brands = [s for s in request.GET.getlist('brand') if s]
    sort = request.GET.get('sort') or default_sort
    if sort not in dict(SORT_OPTIONS):
        sort = default_sort

    qs = base_qs.active().with_relations().with_stock()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(description__icontains=q) | Q(item_code__icontains=q)
            | Q(brand__name__icontains=q) | Q(category__name__icontains=q)
        )
    if selected_categories:
        qs = qs.filter(category__slug__in=selected_categories)
    if selected_brands:
        qs = qs.filter(brand__slug__in=selected_brands)
    # Every filter above joins single-valued foreign keys, so rows cannot duplicate
    # and DISTINCT is not needed.
    qs = _apply_sort(qs, sort, tier)

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)

    context = {
        'title': title,
        'subtitle': subtitle,
        'tier': tier,
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'page_range': list(page_range),
        'total_count': paginator.count,
        'q': q,
        'sort': sort,
        'sort_options': SORT_OPTIONS,
        'selected_categories': selected_categories,
        'selected_brands': selected_brands,
        'has_filters': bool(q or selected_categories or selected_brands),
        'show_hero': show_hero,
    }
    if extra:
        context.update(extra)

    if is_ajax(request):
        html = render_to_string('partials/product_grid.html', context, request=request)
        return json_ok(html=html, count=paginator.count, page=page_obj.number, num_pages=paginator.num_pages)
    return render(request, template, context)


# ---------------------------------------------------------------------------
# Storefront
# ---------------------------------------------------------------------------
# Artwork for the rotating rings in the home hero: (label, file in static/assets/<folder>/).
HERO_CATEGORIES = [
    ('Cereals', 'cereals.jpg'), ('Oils', 'oils.jpg'), ('Drinks', 'drinks.jpg'),
    ('Soaps', 'soaps.jpg'), ('Flour', 'flour.jpg'),
]
HERO_BRANDS = [
    ('Ajab', 'ajab.jpeg'), ('Coca-Cola', 'cocacola.png'), ('Soko', 'soko.jpeg'),
    ('Del Monte', 'delmonte.png'), ('Kensalt', 'kensalt.jpeg'), ('Ketepa', 'ketepa.jpeg'),
    ('Jetlak', 'jetlak.png'), ('Tropical Heat', 'tropicalheat.jpeg'), ('Kapa Oil', 'kapa.png'),
    ('Pembe', 'pembe.jpeg'), ('EXE', 'exe.png'),
]
TRENDING_RAIL_SIZE = 12


def home(request):
    active = Product.objects.active().with_relations().with_stock()
    context = {
        # Flagged products lead the rail; best sellers and new arrivals top it up
        # so it never runs short on a small catalogue.
        'trending': active.order_by('-is_trending', '-is_best_seller', '-created_at')[:TRENDING_RAIL_SIZE],
        'hero_categories': HERO_CATEGORIES,
        'hero_brands': HERO_BRANDS,
    }
    return render(request, 'core/home.html', context)


def products(request):
    return catalog(
        request, Product.objects.all(),
        title="Product Catalogue",
        subtitle="Every SKU we distribute, priced for your account.",
    )


def retailers(request):
    return catalog(
        request, Product.objects.all(),
        title="Retailers Shop",
        subtitle="Shop-ready FMCG lines at retail prices with next-day delivery across Nairobi.",
        tier='retail',
        extra={'tier_notice': 'retail'},
    )


def wholesalers(request):
    # Only products that actually carry a wholesale price belong on this page.
    return catalog(
        request, Product.objects.with_wholesale_price(),
        title="Wholesalers Shop",
        subtitle="Bale and carton pricing straight from the manufacturer for verified wholesale accounts.",
        tier='wholesale',
        extra={'tier_notice': 'wholesale'},
    )


def offers(request):
    return catalog(
        request, Product.objects.on_offer(price_tier_for(request.user)),
        title="Offers & Deals",
        subtitle="Every product with a reduced price. Prices update daily.",
        default_sort='discount',
        extra={'is_offers': True},
    )


def search(request):
    q = (request.GET.get('q') or '').strip()
    return catalog(
        request, Product.objects.all(),
        title=f'Results for “{q}”' if q else "Search",
        subtitle="" if q else "Type a product, brand or category name to search the catalogue.",
        show_hero=False,
        extra={'is_search': True},
    )


@require_GET
def search_suggest(request):
    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return json_ok(products=[], categories=[], brands=[])
    tier = price_tier_for(request.user)
    products_qs = Product.objects.active().with_relations().filter(
        Q(name__icontains=q) | Q(brand__name__icontains=q) | Q(item_code__icontains=q)
    ).order_by('-is_best_seller', 'name')[:6]
    return json_ok(
        products=[{
            'id': p.id, 'name': p.name, 'brand': p.brand.name if p.brand else '',
            'price': float(p.price_for(tier)), 'url': p.get_absolute_url(), 'image': p.image_url,
            'has_image': p.has_image, 'initials': p.initials, 'hue': p.placeholder_hue,
        } for p in products_qs],
        categories=[{'name': c.name, 'url': c.get_absolute_url()} for c in Category.objects.filter(name__icontains=q)[:4]],
        brands=[{'name': b.name, 'url': b.get_absolute_url()} for b in Brand.objects.filter(name__icontains=q)[:4]],
    )


def categories(request):
    cats = (
        Category.objects.annotate(product_count=Count('products', filter=Q(products__is_active=True)))
        .filter(product_count__gt=0).order_by('name')
    )
    return render(request, 'core/categories.html', {'categories': cats})


def brands(request):
    brand_list = (
        Brand.objects.annotate(product_count=Count('products', filter=Q(products__is_active=True)))
        .filter(product_count__gt=0).order_by('name')
    )
    return render(request, 'core/brands.html', {'brands': brand_list})


def product_detail(request, pk):
    product = get_object_or_404(Product.objects.with_relations().with_stock(), pk=pk, is_active=True)
    related = Product.objects.active().with_relations().with_stock().exclude(pk=pk)
    same_category = related.filter(category=product.category)[:8] if product.category else related[:8]
    same_brand = related.filter(brand=product.brand).exclude(pk__in=[p.pk for p in same_category])[:4] if product.brand else []
    variants = Product.objects.active().with_relations().filter(name=product.name).exclude(pk=pk)
    cart = Cart(request)
    context = {
        'product': product,
        'related_products': same_category,
        'brand_products': same_brand,
        'variants': variants,
        'in_cart_qty': cart.quantity_of(product.id),
        'in_stock': product.in_stock,
        'can_buy': product.in_stock and product.is_purchasable,
    }
    # Coming from the retailers/wholesalers pages: keep showing that tier's price
    # (the cart is still charged at the account's tier, and the page says so).
    requested_tier = request.GET.get('tier')
    if requested_tier in (PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE) and requested_tier != cart.tier:
        context['tier'] = requested_tier
        context['tier_notice'] = requested_tier
    return render(request, 'core/product-detail.html', context)


def csv_text(value):
    """A spreadsheet-safe cell: text starting with = + - @ would run as a formula when the
    CSV is opened in Excel or Sheets, so such cells are prefixed with an apostrophe."""
    value = str(value or '')
    if value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def _build_price_list():
    import io
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['Item code', 'Product', 'Category', 'Brand', 'Unit', 'Retail price (KSh)', 'Wholesale price (KSh)',
                     'Was (retail)', 'Was (wholesale)', 'VAT %', 'In stock'])
    products = Product.objects.active().with_relations().with_stock().order_by('category__name', 'name')
    for p in products:
        writer.writerow([
            csv_text(p.item_code), csv_text(p.name), csv_text(p.category.name if p.category else ''),
            csv_text(p.brand.name if p.brand else ''), csv_text(p.pack_size),
            p.retail_price or '', p.wholesale_price or '',
            p.old_price_for(PRICE_TIER_RETAIL) or '', p.old_price_for(PRICE_TIER_WHOLESALE) or '',
            plain_number(p.vat_rate), 'yes' if p.in_stock else 'no',
        ])
    return buffer.getvalue()


def price_list(request):
    """Downloadable CSV price list generated from the live catalogue. It is cached for a few
    minutes (and dropped when the catalogue or stock changes) so anonymous downloads cannot
    make the server walk the whole catalogue on every request."""
    body = cache.get(PRICE_LIST_CACHE_KEY)
    if body is None:
        body = _build_price_list()
        cache.set(PRICE_LIST_CACHE_KEY, body, settings.PRICE_LIST_CACHE_SECONDS)
    response = HttpResponse(body, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="mahitaji-price-list.csv"'
    return response
