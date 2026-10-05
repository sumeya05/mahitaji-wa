from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q

from .cart import Cart, price_tier_for
from .models import Brand, Category, Coupon, Product, WishlistItem

NAV_CACHE_KEY = 'shop:catalogue-nav'
NAV_CACHE_TTL = 300  # seconds; also invalidated by signals when the catalogue changes


def catalogue_nav():
    """
    Categories and brands (with active-product counts) used by the header,
    mega menu, filters and footer on every page. Computed once and cached,
    and dropped by ``core.signals`` whenever a product, category or brand
    changes, so counts never go stale in-process.
    """
    nav = cache.get(NAV_CACHE_KEY)
    if nav is None:
        active_filter = Q(products__is_active=True)
        categories = list(
            Category.objects.annotate(product_count=Count('products', filter=active_filter))
            .filter(product_count__gt=0)
            .order_by('-product_count', 'name')
        )
        brands = list(
            Brand.objects.annotate(product_count=Count('products', filter=active_filter))
            .filter(product_count__gt=0)
            .order_by('name')
        )
        nav = {
            'categories': categories,
            'brands': brands,
            'product_count': Product.objects.filter(is_active=True).count(),
        }
        cache.set(NAV_CACHE_KEY, nav, NAV_CACHE_TTL)
    return nav


def invalidate_catalogue_nav(**kwargs):
    cache.delete(NAV_CACHE_KEY)


def shop(request):
    """Everything the base layout needs on every page."""
    nav = catalogue_nav()

    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(WishlistItem.objects.filter(user=request.user).values_list('product_id', flat=True))

    return {
        'cart': Cart(request),
        'nav_categories': nav['categories'][:8],
        'all_categories': nav['categories'],
        'all_brands': nav['brands'],
        'wishlist_ids': wishlist_ids,
        'price_tier': price_tier_for(request.user),
        'site': settings.SITE_INFO,
        'promo_coupon': promoted_coupon(),
    }


def promoted_coupon():
    """The coupon the offer pop-up advertises: the best promoted code that can be used today."""
    for coupon in Coupon.objects.filter(promote=True, active=True).order_by('-percent'):
        if Coupon.usable(coupon.code):
            return coupon
    return None
