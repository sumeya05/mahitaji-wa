"""
Storefront, account, checkout, payment and API views for Mahitaji.

Conventions
-----------
* AJAX endpoints answer JSON shaped as ``{"ok": true, ...}`` or
  ``{"ok": false, "error": "summary", "errors": {"field": ["msg"]}}``.
* Any view that changes state is POST-only.
* Prices shown/charged depend on the customer's tier (retail/wholesale), see cart.py.
"""
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from rest_framework import permissions, viewsets

from .cart import Cart, price_tier_for
from .context_processors import catalogue_nav
from .forms import (
    AccountForm, AddressForm, CheckoutForm, ContactForm, NewsletterForm,
    PasswordChangeForm, RegisterForm, normalize_phone,
)
from .models import (
    PRICE_TIER_RETAIL, PRICE_TIER_WHOLESALE, Address, Brand, Category, CustomerProfile, MpesaTransaction,
    NewsletterSubscriber, Order, OrderItem, Product, WishlistItem,
)
from .serializers import BrandSerializer, CategorySerializer, OrderSerializer, ProductSerializer
from .services import MpesaError, initiate_stk_push as mpesa_stk_push, process_stk_callback

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
        'application/json' in request.headers.get('accept', '')


def json_ok(**payload):
    payload.setdefault('ok', True)
    return JsonResponse(payload)


def json_error(message, status=400, errors=None):
    return JsonResponse({'ok': False, 'error': message, 'errors': errors or {}}, status=status)


def form_errors(form):
    return {field: [str(e) for e in errs] for field, errs in form.errors.items()}


def request_data(request):
    """Accept JSON bodies as well as regular form posts."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body or b'{}')
        except ValueError:
            return {}
    return request.POST


def get_profile(user):
    profile, _ = CustomerProfile.objects.get_or_create(
        user=user, defaults={'phone_number': '', 'contact_person': user.get_full_name()}
    )
    # Populate both sides of the one-to-one so later ``user.customerprofile`` /
    # ``profile.user`` accesses (tier lookup, templates) do not re-query.
    user.customerprofile = profile
    return profile


def safe_next_url(request, fallback='dashboard'):
    candidate = request.POST.get('next') or request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return reverse(fallback)


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


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
def _cart_response(request, cart, message='', product=None):
    payload = {'cart': cart.summary(), 'message': message}
    if is_ajax(request):
        payload['drawer_html'] = render_to_string('partials/cart_drawer_items.html', {'cart': cart}, request=request)
        if product is not None:
            payload['product'] = {'id': product.id, 'name': product.name, 'qty': cart.quantity_of(product.id)}
        return json_ok(**payload)
    if message:
        messages.success(request, message)
    return redirect(request.META.get('HTTP_REFERER') or 'shopping-cart')


def shopping_cart(request):
    return render(request, 'core/shopping-cart.html', {'cart': Cart(request)})


def mini_cart(request):
    return render(request, 'partials/cart_drawer_items.html', {'cart': Cart(request)})


@require_POST
def cart_add(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = int(data.get('product_qty') or data.get('qty') or 1)
    except (TypeError, ValueError):
        return json_error("Invalid product.")
    product = get_object_or_404(Product, id=product_id, is_active=True)
    cart = Cart(request)
    cart.add(product, qty)
    return _cart_response(request, cart, f"{product.name} added to your cart.", product)


@require_POST
def cart_update(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
        qty = int(data.get('product_qty') or data.get('qty') or 1)
    except (TypeError, ValueError):
        return json_error("Invalid quantity.")
    cart = Cart(request)
    cart.update(product_id, qty)
    line_total = 0
    for item in cart:
        if item['product'].id == product_id:
            line_total = float(item['total_price'])
    if is_ajax(request):
        payload = {'cart': cart.summary(), 'line_total': line_total, 'product_id': product_id,
                   'drawer_html': render_to_string('partials/cart_drawer_items.html', {'cart': cart}, request=request)}
        return json_ok(**payload)
    return redirect('shopping-cart')


@require_POST
def cart_delete(request):
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
    except (TypeError, ValueError):
        return json_error("Invalid product.")
    cart = Cart(request)
    cart.delete(product_id)
    return _cart_response(request, cart, "Item removed from your cart.")


# ---------------------------------------------------------------------------
# Checkout & orders
# ---------------------------------------------------------------------------
@login_required
def checkout(request):
    cart = Cart(request)
    if cart.is_empty:
        messages.info(request, "Your cart is empty. Add a few products before checking out.")
        return redirect('products')
    profile = get_profile(request.user)
    primary = profile.primary_address
    return render(request, 'core/checkout.html', {
        'cart': cart,
        'profile': profile,
        'addresses': profile.addresses.all(),
        'primary_address': primary,
        'mpesa_enabled': bool(settings.MPESA_CALLBACK_URL and settings.MPESA_CONSUMER_KEY),
    })


def _send_order_confirmation(order):
    if not order.email:
        return
    try:
        body = render_to_string('core/emails/order_confirmation.txt', {'order': order, 'site': settings.SITE_INFO})
        recipients = [order.email]
        if settings.ORDER_NOTIFICATION_EMAIL:
            recipients.append(settings.ORDER_NOTIFICATION_EMAIL)
        send_mail(f"Order {order.order_number} confirmed", body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
    except Exception:  # never let email problems break checkout
        logger.exception("Could not send confirmation for %s", order.order_number)


@login_required
@require_POST
def place_order(request):
    cart = Cart(request)
    if cart.is_empty:
        return json_error("Your cart is empty.", status=400)

    form = CheckoutForm(request_data(request))
    if not form.is_valid():
        return json_error("Please check the highlighted fields.", errors=form_errors(form))
    data = form.cleaned_data
    profile = get_profile(request.user)

    with transaction.atomic():
        order = Order.objects.create(
            order_number=Order.generate_order_number(),
            customer=profile,
            full_name=f"{data['first_name'].strip()} {data['last_name'].strip()}",
            email=data['email'],
            phone=data['phone'],
            address=data['address'].strip(),
            city=data['city'],
            notes=data.get('notes', '').strip(),
            payment_method=data['payment_method'],
            total_amount=cart.get_total_price(),
            status=Order.STATUS_PENDING,
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=item['product'], quantity=item['qty'], price_at_purchase=item['price'])
            for item in cart
        ])
        if not profile.phone_number:
            profile.phone_number = data['phone']
            profile.save(update_fields=['phone_number'])
        if data.get('save_address') or not profile.addresses.exists():
            Address.objects.update_or_create(
                customer=profile, is_primary=True,
                defaults={'label': 'Delivery Address', 'physical_address': order.address, 'city': order.city},
            )

    cart.clear()
    _send_order_confirmation(order)

    payment = {'sent': False, 'message': ''}
    if order.payment_method == Order.PAYMENT_MPESA:
        try:
            mpesa_stk_push(order, data['mpesa_phone'])
            payment = {'sent': True, 'message': 'Check your phone and enter your M-Pesa PIN to complete payment.'}
        except MpesaError as exc:
            payment = {'sent': False, 'message': str(exc)}

    return json_ok(
        order_number=order.order_number,
        order_id=order.id,
        payment_method=order.payment_method,
        payment=payment,
        redirect_url=reverse('order-success', args=[order.order_number]),
        status_url=reverse('check_payment_status', args=[order.order_number]),
    )


def _owned_order(request, order_number):
    return get_object_or_404(
        Order.objects.select_related('customer').prefetch_related('items__product'),
        order_number=order_number, customer__user=request.user,
    )


@login_required
def order_success(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-success.html', {
        'order': order,
        'mpesa_txn': getattr(order, 'mpesa_payment', None),
        'awaiting_payment': order.can_pay,
    })


@login_required
def order_detail(request, order_number):
    order = _owned_order(request, order_number)
    return render(request, 'core/order-detail.html', {
        'order': order,
        'mpesa_txn': MpesaTransaction.objects.filter(order=order).first(),
        'awaiting_payment': order.can_pay,
    })


@login_required
@require_POST
def order_cancel(request, order_number):
    order = _owned_order(request, order_number)
    if not order.can_cancel:
        messages.error(request, "This order can no longer be cancelled. Please contact support.")
    else:
        order.status = Order.STATUS_CANCELLED
        order.save()
        messages.success(request, f"Order {order.order_number} has been cancelled.")
    return redirect('order_detail', order_number=order.order_number)


@login_required
def get_order_details(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), id=order_id, customer__user=request.user)
    return render(request, 'core/account/order_items_fragment.html', {'order': order})


# ---------------------------------------------------------------------------
# Payments (M-Pesa)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def initiate_stk_push(request):
    data = request_data(request)
    order_number = data.get('order_number')
    if order_number:
        order = _owned_order(request, order_number)
    else:
        order = get_object_or_404(Order, id=data.get('order_id'), customer__user=request.user)
    if order.is_paid:
        return json_error("This order is already paid.")
    if not order.can_pay:
        return json_error(f"This order is {order.get_status_display().lower()} and can no longer be paid.")
    try:
        txn = mpesa_stk_push(order, data.get('phone') or order.phone)
    except MpesaError as exc:
        return json_error(str(exc), status=502)
    return json_ok(checkout_id=txn.checkout_request_id, message="Check your phone and enter your M-Pesa PIN.")


@login_required
@require_GET
def check_payment_status(request, order_number):
    order = _owned_order(request, order_number)
    txn = MpesaTransaction.objects.filter(order=order).first()
    if order.is_paid:
        status = 'paid'
    elif order.status == Order.STATUS_FAILED:
        status = 'failed'
    else:
        status = 'pending'
    return json_ok(
        status=status,
        order_status=order.status,
        receipt=txn.receipt_number if txn else None,
        description=txn.response_description if txn else '',
    )


@csrf_exempt
@require_POST
def mpesa_callback(request):
    try:
        payload = json.loads(request.body or b'{}')
        txn, success = process_stk_callback(payload)
        logger.info("M-Pesa callback for %s: %s", txn.order.order_number, 'success' if success else 'failed')
    except MpesaTransaction.DoesNotExist:
        logger.warning("M-Pesa callback for unknown CheckoutRequestID: %s", request.body[:200])
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Malformed M-Pesa callback: %s", exc)
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Malformed payload"}, status=400)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        login_input = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        username = login_input
        if '@' in login_input:
            matched = User.objects.filter(email__iexact=login_input).order_by('id').first()
            if matched:
                username = matched.username
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)
            if not request.POST.get('remember_me'):
                request.session.set_expiry(0)
            next_url = safe_next_url(request)
            if is_ajax(request):
                return json_ok(redirect_url=next_url)
            return redirect(next_url)

        error_msg = "We couldn't sign you in with those details. Check your email/username and password."
        if is_ajax(request):
            return json_error(error_msg, status=400)
        messages.error(request, error_msg)

    return render(request, 'core/auth/login.html', {'next': request.GET.get('next', '')})


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to Mahitaji, {user.first_name}! Your account is ready.")
            if is_ajax(request):
                return json_ok(redirect_url=safe_next_url(request))
            return redirect(safe_next_url(request))
        if is_ajax(request):
            return json_error("Please fix the highlighted fields.", errors=form_errors(form))
    else:
        form = RegisterForm()
    return render(request, 'core/auth/register.html', {'form': form})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    logout(request)
    if is_ajax(request):
        return json_ok(redirect_url=reverse('home'))
    messages.info(request, "You have been signed out.")
    return redirect('home')


@require_http_methods(["GET", "POST"])
def custom_password_reset(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                email_template_name='core/auth/password_reset_email.html',
                subject_template_name='core/auth/password_reset_subject.txt',
            )
            # Always behave the same, so the form can't be used to enumerate accounts.
            if is_ajax(request):
                return json_ok(redirect_url=reverse('password_reset_done'))
            return redirect('password_reset_done')
        if is_ajax(request):
            return json_error("Enter a valid email address.", errors=form_errors(form))
    return render(request, 'core/auth/password_reset.html')


@require_http_methods(["GET", "POST"])
def custom_password_reset_confirm(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist, UnicodeDecodeError):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'core/auth/password_reset_invalid.html', status=400)

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            if is_ajax(request):
                return json_ok(redirect_url=reverse('password_reset_complete'))
            return redirect('password_reset_complete')
        if is_ajax(request):
            return json_error("Please check the password requirements.", errors=form_errors(form))
    else:
        form = SetPasswordForm(user)
    return render(request, 'core/auth/password_reset_confirm.html', {'form': form})


def password_reset_done(request):
    return render(request, 'core/auth/password_reset_done.html')


def password_reset_complete(request):
    return render(request, 'core/auth/password_reset_complete.html')


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
def _account_context(request, section):
    profile = get_profile(request.user)
    return {
        'profile': profile,
        'section': section,
        'order_count': profile.orders.count(),
        'wishlist_count': WishlistItem.objects.filter(user=request.user).count(),
    }


@login_required
def dashboard(request):
    ctx = _account_context(request, 'dashboard')
    orders = ctx['profile'].orders.prefetch_related('items')
    ctx.update({
        'recent_orders': orders[:5],
        'pending_count': orders.filter(status__in=[Order.STATUS_PENDING, Order.STATUS_PAID, Order.STATUS_SHIPPED]).count(),
        'total_spent': sum((o.total_amount for o in orders if o.is_paid), 0),
        'primary_address': ctx['profile'].primary_address,
        'recent_wishlist': WishlistItem.objects.filter(user=request.user).select_related('product__brand')[:4],
    })
    return render(request, 'core/account/dashboard.html', ctx)


@login_required
def transactions(request):
    ctx = _account_context(request, 'orders')
    status = request.GET.get('status', '')
    orders = ctx['profile'].orders.prefetch_related('items__product')
    if status:
        orders = orders.filter(status=status)
    paginator = Paginator(orders, 10)
    ctx.update({
        'page_obj': paginator.get_page(request.GET.get('page')),
        'status_filter': status,
        'status_choices': Order.STATUS_CHOICES,
        'payments': MpesaTransaction.objects.filter(order__customer=ctx['profile']).select_related('order')[:10],
    })
    return render(request, 'core/account/orders.html', ctx)


@login_required
@require_http_methods(["GET", "POST"])
def addresses(request):
    ctx = _account_context(request, 'addresses')
    profile = ctx['profile']
    if request.method == 'POST':
        pk = request.POST.get('address_id')
        instance = get_object_or_404(Address, pk=pk, customer=profile) if pk else None
        form = AddressForm(request.POST, instance=instance)
        if form.is_valid():
            address = form.save(commit=False)
            address.customer = profile
            if not profile.addresses.exclude(pk=address.pk).exists():
                address.is_primary = True
            address.save()
            messages.success(request, "Address saved.")
            return redirect('addresses')
        messages.error(request, "Please check the address form.")
    else:
        form = AddressForm()
    ctx.update({'form': form, 'address_list': profile.addresses.all()})
    return render(request, 'core/account/addresses.html', ctx)


@login_required
@require_POST
def address_delete(request, pk):
    profile = get_profile(request.user)
    address = get_object_or_404(Address, pk=pk, customer=profile)
    was_primary = address.is_primary
    address.delete()
    if was_primary:
        remaining = profile.addresses.first()
        if remaining:
            remaining.is_primary = True
            remaining.save()
    messages.success(request, "Address removed.")
    return redirect('addresses')


@login_required
@require_http_methods(["GET", "POST"])
def payment_methods(request):
    ctx = _account_context(request, 'payments')
    profile = ctx['profile']
    if request.method == 'POST':
        phone = normalize_phone(request.POST.get('mpesa_number'))
        if not phone:
            messages.error(request, "Enter a valid Safaricom number, e.g. 0712 345 678.")
        else:
            profile.phone_number = phone
            profile.save(update_fields=['phone_number'])
            messages.success(request, "M-Pesa number updated.")
            return redirect('payment_methods')
    ctx['payments'] = MpesaTransaction.objects.filter(order__customer=profile).select_related('order')[:20]
    return render(request, 'core/account/payments.html', ctx)


@login_required
@require_http_methods(["GET", "POST"])
def update_account(request):
    """Account settings page. Handles the profile form and the password form."""
    ctx = _account_context(request, 'settings')
    user, profile = request.user, ctx['profile']
    account_form = AccountForm(user, initial={
        'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
        'business_name': profile.business_name, 'phone_number': profile.phone_number, 'tax_id': profile.tax_id,
    })
    password_form = PasswordChangeForm(user)

    if request.method == 'POST':
        form_type = request.POST.get('form_type', 'account')
        if form_type == 'password':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user.set_password(password_form.cleaned_data['new_password'])
                user.save()
                update_session_auth_hash(request, user)
                if is_ajax(request):
                    return json_ok(message="Password updated.")
                messages.success(request, "Password updated.")
                return redirect('update_account')
            if is_ajax(request):
                return json_error("Please check the password fields.", errors=form_errors(password_form))
        else:
            account_form = AccountForm(user, request.POST)
            if account_form.is_valid():
                data = account_form.cleaned_data
                user.first_name, user.last_name, user.email = data['first_name'], data['last_name'], data['email']
                user.save()
                profile.business_name = data.get('business_name') or None
                profile.phone_number = data['phone_number']
                profile.tax_id = data.get('tax_id')
                profile.contact_person = user.get_full_name()
                profile.save()
                if is_ajax(request):
                    return json_ok(message="Profile updated.")
                messages.success(request, "Profile updated.")
                return redirect('update_account')
            if is_ajax(request):
                return json_error("Please check the highlighted fields.", errors=form_errors(account_form))

    ctx.update({'account_form': account_form, 'password_form': password_form})
    return render(request, 'core/account/settings.html', ctx)


@login_required
def wishlist(request):
    ctx = _account_context(request, 'wishlist')
    ctx['items'] = WishlistItem.objects.filter(user=request.user).select_related('product__brand', 'product__category', 'product__unit_of_measure')
    return render(request, 'core/account/wishlist.html', ctx)


@require_POST
def wishlist_toggle(request):
    if not request.user.is_authenticated:
        return json_error("Sign in to save products to your wishlist.", status=401)
    data = request_data(request)
    try:
        product_id = int(data.get('product_id'))
    except (TypeError, ValueError):
        return json_error("Invalid product.", status=400)
    product = get_object_or_404(Product, id=product_id, is_active=True)
    item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
    if not created:
        item.delete()
    count = WishlistItem.objects.filter(user=request.user).count()
    if is_ajax(request):
        return json_ok(added=created, count=count,
                       message=f"{product.name} {'saved to' if created else 'removed from'} your wishlist.")
    messages.success(request, f"{product.name} {'saved to' if created else 'removed from'} your wishlist.")
    return redirect(request.META.get('HTTP_REFERER') or 'wishlist')


# ---------------------------------------------------------------------------
# Help desk, company pages, contact & newsletter
# ---------------------------------------------------------------------------
def pickups(request):
    return render(request, 'core/pages/pickups.html')


def payment_info(request):
    return render(request, 'core/pages/payment_info.html')


def returns(request):
    return render(request, 'core/pages/returns.html')


def faqs(request):
    return render(request, 'core/pages/faqs.html')


def terms(request):
    return render(request, 'core/pages/terms.html')


def about(request):
    return render(request, 'core/pages/about.html')


def statement(request):
    return render(request, 'core/pages/statement.html')


def location(request):
    return render(request, 'core/pages/location.html')


@require_http_methods(["GET", "POST"])
def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            message = form.save()
            try:
                send_mail(
                    f"[Mahitaji] {message.get_inquiry_type_display()} from {message.full_name}",
                    f"{message.message}\n\nFrom: {message.full_name} <{message.email}> {message.phone}\nBusiness: {message.business_name}",
                    settings.DEFAULT_FROM_EMAIL, [settings.SITE_INFO['email']], fail_silently=True,
                )
            except Exception:
                logger.exception("Contact email failed")
            if is_ajax(request):
                return json_ok(message="Thanks! Our team will get back to you within one business day.")
            messages.success(request, "Thanks! Our team will get back to you within one business day.")
            return redirect('contact')
        if is_ajax(request):
            return json_error("Please check the highlighted fields.", errors=form_errors(form))
    else:
        initial = {}
        if request.user.is_authenticated:
            profile = getattr(request.user, 'customerprofile', None)
            initial = {'full_name': request.user.get_full_name(), 'email': request.user.email,
                       'business_name': profile.business_name if profile else '', 'phone': profile.phone_number if profile else ''}
        form = ContactForm(initial=initial)
    return render(request, 'core/pages/contact.html', {'form': form})


@require_POST
def newsletter_subscribe(request):
    form = NewsletterForm(request_data(request))
    if form.is_valid():
        NewsletterSubscriber.objects.get_or_create(email=form.cleaned_data['email'])
        msg = "You're on the list. Expect offers and stock alerts in your inbox."
        if is_ajax(request):
            return json_ok(message=msg)
        messages.success(request, msg)
    else:
        if is_ajax(request):
            return json_error("Enter a valid email address.", errors=form_errors(form))
        messages.error(request, "Enter a valid email address.")
    return redirect(request.META.get('HTTP_REFERER') or 'home')


# ---------------------------------------------------------------------------
# AI assistant
# ---------------------------------------------------------------------------
def _assistant_product_context(message, tier):
    words = [w.strip('?.,!').lower() for w in message.split() if len(w.strip('?.,!')) > 2][:6]
    if not words:
        return []
    query = Q()
    for word in words:
        query |= Q(name__icontains=word) | Q(brand__name__icontains=word) | Q(category__name__icontains=word)
    return list(Product.objects.active().with_relations().filter(query).order_by('-is_best_seller', 'name')[:6]), words


@require_POST
def ai_assistant_chat(request):
    user_message = (request_data(request).get('message') or '').strip()
    if not user_message:
        return json_error("Say something first.")
    tier = price_tier_for(request.user)
    found = _assistant_product_context(user_message, tier)
    matches = found[0] if found else []
    product_lines = "\n".join(
        f"- {p.name} ({p.brand.name if p.brand else 'Mahitaji'}) — KSh {p.price_for(tier):,.0f} per {p.pack_size or 'unit'}; link: /product/{p.id}/"
        for p in matches
    )

    name = request.user.get_full_name() if request.user.is_authenticated else "a visitor"
    site = settings.SITE_INFO
    system_prompt = (
        "You are the Mahitaji Assistant for Mahitaji Enterprises Ltd, an FMCG wholesaler and retailer in Nairobi, Kenya. "
        "Answer briefly and helpfully in plain text (no markdown). Prices are in Kenyan shillings. "
        f"Delivery: within 24 hours in Nairobi, 2-3 days upcountry; self pick-up at {site['address']}. "
        f"Payment: M-Pesa or cash on delivery. Support: {site['phone']}, {site['email']}. "
        f"The customer is {name} on the {tier} price tier. "
        + (f"Relevant catalogue items:\n{product_lines}" if product_lines else "No catalogue items matched their message.")
    )

    if not settings.GEMINI_API_KEY:
        if matches:
            reply = "Here is what I found in our catalogue:\n" + product_lines.replace('; link: ', ' — ')
        else:
            reply = (f"I can help with products, orders, delivery and payments. Call us on {site['phone']} "
                     "or browse the catalogue for live prices.")
        return json_ok(reply=reply, products=[{'id': p.id, 'name': p.name, 'url': p.get_absolute_url()} for p in matches])

    try:
        import google.generativeai as genai  # imported lazily: optional dependency
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL, system_instruction=system_prompt)
        response = model.generate_content(user_message)
        reply = (response.text or '').strip() or "Sorry, I didn't catch that. Could you rephrase?"
    except Exception as exc:
        logger.warning("Gemini request failed: %s", exc)
        if "429" in str(exc):
            reply = "I'm helping a lot of retailers right now. Please try again in about 30 seconds."
        else:
            reply = ("I'm having trouble connecting right now. " +
                     (f"Meanwhile, here is what matched in our catalogue:\n{product_lines}" if product_lines
                      else f"Please call {site['phone']} and our team will help."))
    return json_ok(reply=reply, products=[{'id': p.id, 'name': p.name, 'url': p.get_absolute_url()} for p in matches])


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def error_404(request, exception=None):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = 'slug'


class BrandViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    lookup_field = 'slug'


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    # ``stock_total`` feeds Product.current_stock so the list endpoint does not
    # run one ledger aggregate per product.
    queryset = Product.objects.active().with_relations().annotate(stock_total=Sum('stock_ledger__quantity'))
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get('category'):
            queryset = queryset.filter(category__slug=params['category'])
        if params.get('brand'):
            queryset = queryset.filter(brand__slug=params['brand'])
        if params.get('q'):
            q = params['q']
            queryset = queryset.filter(Q(name__icontains=q) | Q(item_code__icontains=q) | Q(brand__name__icontains=q))
        return queryset.order_by('name')


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer
    lookup_field = 'order_number'

    def get_queryset(self):
        return Order.objects.filter(customer__user=self.request.user).prefetch_related('items__product')
