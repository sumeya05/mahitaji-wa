import hashlib
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..cart import price_tier_for
from ..models import PRICE_TIER_WHOLESALE

register = template.Library()


@register.filter
def ksh(value):
    """Format a number as Kenyan shillings: 'KSh 3,250' (no cents when whole)."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    if amount == amount.to_integral_value():
        return f"KSh {int(amount):,}"
    return f"KSh {amount:,.2f}"


@register.filter
def money(value):
    """Plain number with thousands separators, used inside JS-updated nodes."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    if amount == amount.to_integral_value():
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


@register.simple_tag(takes_context=True)
def price_tier(context):
    forced = context.get('tier')
    if forced:
        return forced
    request = context.get('request')
    return price_tier_for(getattr(request, 'user', None))


@register.simple_tag(takes_context=True)
def product_price(context, product):
    return product.price_for(price_tier(context))


@register.simple_tag(takes_context=True)
def product_url(context, product):
    """
    Link to the product page, keeping the tier the customer is browsing at.

    The retailers/wholesalers pages force a tier that may differ from the
    account's own tier; without ``?tier=`` the detail page would fall back to
    the account tier and show a different price than the card they clicked.
    """
    url = product.get_absolute_url()
    request = context.get('request')
    forced = context.get('tier')
    if forced and forced != price_tier_for(getattr(request, 'user', None)):
        return f"{url}?tier={forced}"
    return url


@register.simple_tag(takes_context=True)
def tier_label(context):
    return "Wholesale price" if price_tier(context) == PRICE_TIER_WHOLESALE else "Retail price"


@register.simple_tag(takes_context=True)
def product_price_label(context, product):
    """Label for the price actually shown: says "Retail price" when a wholesale
    viewer sees a product that has no wholesale price."""
    return "Wholesale price" if product.tier_used(price_tier(context)) == PRICE_TIER_WHOLESALE else "Retail price"


@register.simple_tag(takes_context=True)
def product_old_price(context, product):
    """Previous price for the tier being shown, or None. Never the other tier's price."""
    return product.old_price_for(price_tier(context))


@register.simple_tag(takes_context=True)
def product_discount(context, product):
    return product.discount_percentage_for(price_tier(context))


@register.simple_tag(takes_context=True)
def product_saving(context, product):
    return product.amount_saved_for(price_tier(context))


@register.filter
def in_wishlist(product, wishlist_ids):
    try:
        return product.id in wishlist_ids
    except TypeError:
        return False


@register.simple_tag
def stars(rating, max_stars=5):
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    rating = max(0, min(max_stars, rating))
    filled = '<i class="fa-solid fa-star"></i>' * rating
    empty = '<i class="fa-regular fa-star"></i>' * (max_stars - rating)
    return mark_safe(f'<span class="stars" aria-label="{rating} out of {max_stars} stars">{filled}{empty}</span>')


@register.simple_tag(takes_context=True)
def qs_replace(context, **kwargs):
    """Rebuild the current query string with some keys replaced (used for pagination/sort links)."""
    request = context['request']
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == '':
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def qs_toggle(context, key, value):
    """Toggle a value inside a multi-valued query param (used by filter chips)."""
    request = context['request']
    params = request.GET.copy()
    values = params.getlist(key)
    value = str(value)
    if value in values:
        values = [v for v in values if v != value]
    else:
        values.append(value)
    params.setlist(key, values)
    params.pop('page', None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag
def status_badge(order):
    return format_html(
        '<span class="badge badge-{}">{}</span>', order.status_tone, order.get_status_display()
    )


@register.filter
def initials(name):
    words = [w for w in str(name or '').split() if w]
    if not words:
        return '?'
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


@register.filter
def hue(value):
    return sum(ord(c) for c in str(value or '')) % 360


@register.simple_tag
def build_url(base, **kwargs):
    query = {k: v for k, v in kwargs.items() if v not in (None, '')}
    return f"{base}?{urlencode(query)}" if query else base


@register.filter
def get_item(mapping, key):
    """Dictionary lookup with a variable key (keys are matched as strings too)."""
    if not mapping:
        return None
    return mapping.get(key, mapping.get(str(key)))


# --- Drawn packs for products without a photo ------------------------------
# First matching rule wins; the text searched is "<name> <category>" in lower case.
PACK_RULES = [
    ('can', r'\b(spray|aerosol|freshener|doom|scouring|tin|canned|corned|sardines?|tuna|coconut milk)\b'),
    ('tub', r'\b(margarine|fat|paste|ghee|yoghurt|yogurt|ice cream)\b'),
    ('jar', r'\b(jam|honey|peanut|spread|jelly|mayonnaise|pickle|coffee|cocoa|jar)\b'),
    ('bar', r'\b(soap|bar)\b'),
    ('sack', r'\b(rice|flour|sugar|salt|maize|meal|beans|grams|peas|lentils?|pulses?|grains?|wheat|ugali|porridge|unga)\b'),
    ('sachet', r'\b(sanitary|condoms?|cotton|mchuzi|mchuuzi|mix|chunks|masala|curry|spices?|sachet|seasoning)\b'),
    ('roll', r'\b(tissue|toilet paper|serviettes?|roll|kitchen towel)\b'),
    ('bottle', r'\b(oil|juice|soda|water|drinks?|squash|cordial|syrup|vinegar|sauce|ketchup|shampoo|lotion|bleach|liquid|wash|'
               r'cleaner|antiseptic|glycerine|malt|non-alcoholic|pet|\d+ml|\d+(\.\d+)?l|ltr|litre)\b'),
]

# Recognisable brand colours; everything else gets a stable colour hashed from the product line.
BRAND_COLOURS = [
    ('coca cola', '#e4002b'), ('sprite', '#008b47'), ('fanta', '#ff8300'), ('dasani', '#0072ce'),
    ('omo', '#0033a0'), ('sunlight', '#f2b800'), ('blue band', '#0057b8'), ('geisha', '#d6457a'),
    ('dettol', '#0f7a4d'), ('harpic', '#1e50a2'), ('jogoo', '#c8102e'), ('exe ', '#b5121b'),
    ('soko', '#f39c12'), ('pearl', '#1a936f'), ('royco', '#c8102e'), ('del monte', '#a6192e'),
    ('kings tea', '#6b2d2d'), ('elianto', '#f5a623'), ('golden fry', '#e0a100'), ('gurmah', '#5b3a29'),
    ('maltz', '#3b2a1a'), ('mortein', '#c0392b'), ('zesta', '#c62828'), ('velvex', '#5aa9c9'),
    ('tena', '#7e57c2'), ('ndhiwa', '#8d6e63'), ('kensalt', '#2a8bd6'), ('amaize', '#e8a317'),
]

PACK_PALETTE = ['#c98a3a', '#b58b4c', '#6b8e23', '#d9a441', '#e0b000', '#7a4a2a', '#e8612c', '#2a8bd6',
                '#5aa9c9', '#c7803d', '#e74c3c', '#d6457a', '#c0392b', '#8e44ad', '#16a085', '#2c3e50',
                '#1a936f', '#f39c12', '#3d5a80', '#9b2226']

_SIZE_TOKENS = [re.compile(r'\b\d+\s*x(?=\s*\d)', re.I), re.compile(r'x\s*\d+\b', re.I),
                re.compile(r'\b\d+(\.\d+)?\s*(kg|ml|ltr|litre|g|l|pcs?|s)\b', re.I), re.compile(r'\bpet\b', re.I)]


@register.filter
def pack_shape(product):
    """Which drawn pack to show for a product without a photo (bottle, can, jar, tub, bar, sack, sachet, roll, box)."""
    name = str(getattr(product, 'name', '') or '').lower()
    category = str(getattr(getattr(product, 'category', None), 'name', '') or '').lower()
    for text in (name, category):  # the product name is a better clue than its category
        for shape, pattern in PACK_RULES:
            if re.search(pattern, text):
                return shape
    return 'box'


@register.filter
def pack_color(product):
    """A stable colour for a product line, so 'X 500G' and 'X 500G X 12' match but different lines differ."""
    name = str(getattr(product, 'name', '') or '')
    lowered = f" {name.lower()} "
    for needle, colour in BRAND_COLOURS:
        if needle in lowered:
            return colour
    line = name
    for pattern in _SIZE_TOKENS:
        line = pattern.sub(' ', line)
    line = ' '.join(line.split()).lower() or name.lower() or 'x'
    digest = hashlib.md5(line.encode('utf-8')).hexdigest()
    return PACK_PALETTE[int(digest[:2], 16) % len(PACK_PALETTE)]
