"""
Public catalogue: home page, product listings (catalogue / retailers / wholesalers / offers), search, categories, brands and the product page.
"""
import csv
import logging

from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from ..cart import Cart, price_tier_for
from ..context_processors import catalogue_nav
from ..models import (
    PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE, Brand, Category, Product,
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
    price_field = 'wholesale_price' if tier == PRICE_TIER_WHOLESALE else 'retail_price'
    if sort == 'name':
        return queryset.order_by('name')
    if sort == 'price_asc':
        return queryset.order_by(F(price_field).asc(nulls_last=True), 'name')
    if sort == 'price_desc':
        return queryset.order_by(F(price_field).desc(nulls_last=True), 'name')
    if sort == 'newest':
        return queryset.order_by('-created_at', 'name')
    if sort == 'discount':
        old_field = 'old_wholesale_price' if tier == PRICE_TIER_WHOLESALE else 'old_price'
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

    qs = base_qs.active().with_relations()
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
def home(request):
    active = Product.objects.active().with_relations()
    tier = price_tier_for(request.user)
    nav = catalogue_nav()  # cached categories/brands with product counts
    context = {
        'new_products': active.order_by('-created_at')[:8],
        'top_offers': _apply_sort(active.on_offer(tier), 'discount', tier)[:8],
        'bestsellers': active.filter(is_best_seller=True).order_by('name')[:8],
        'trending': active.filter(is_trending=True).order_by('-created_at')[:8],
        'top_categories': nav['categories'][:8],
        'stats': {
            'products': nav['product_count'],
            'brands': len(nav['brands']),
            'categories': len(nav['categories']),
        },
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
    product = get_object_or_404(Product.objects.with_relations(), pk=pk, is_active=True)
    related = Product.objects.active().with_relations().exclude(pk=pk)
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
        'in_stock': product.in_stock,  # evaluated once; the template uses it three times
    }
    # Coming from the retailers/wholesalers pages: keep showing that tier's price
    # (the cart is still charged at the account's tier, and the page says so).
    requested_tier = request.GET.get('tier')
    if requested_tier in (PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE) and requested_tier != cart.tier:
        context['tier'] = requested_tier
        context['tier_notice'] = requested_tier
    return render(request, 'core/product-detail.html', context)


def price_list(request):
    """Downloadable CSV price list generated from the live catalogue, so it never goes stale."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="mahitaji-price-list.csv"'
    writer = csv.writer(response)
    writer.writerow(['Item code', 'Product', 'Category', 'Brand', 'Unit', 'Retail price (KSh)', 'Wholesale price (KSh)',
                     'Was (retail)', 'Was (wholesale)', 'In stock'])
    products = Product.objects.active().with_relations().order_by('category__name', 'name')
    for p in products:
        writer.writerow([
            p.item_code or '', p.name, p.category.name if p.category else '', p.brand.name if p.brand else '',
            p.pack_size, p.retail_price or '', p.wholesale_price or '',
            p.old_price_for(PRICE_TIER_RETAIL) or '', p.old_price_for(PRICE_TIER_WHOLESALE) or '',
            'yes' if p.in_stock else 'no',
        ])
    return response
