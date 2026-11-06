"""
JSON API for the Mahitaji mobile app, mounted at /api/v1/.

The app signs in with a token (``Authorization: Token <key>``) instead of a session cookie,
so these views use DRF token authentication only: no cookies, no CSRF. Every rule the
website applies is reused rather than repeated:

* prices come from ``Cart`` / ``Product.price_for`` at the signed-in customer's tier;
* the app keeps its cart on the phone and sends the lines with each quote or order; they
  are priced, stock-checked and coupon-checked by the same ``Cart`` class the website uses;
* orders are placed by ``checkout.create_order``, payments go through ``services``;
* sign-in shares the website's failed-attempt limits.

Errors are answered as ``{"error": "summary", "errors": {"field": ["msg"]}}``.
"""
import logging
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import send_mail
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import throttle
from ..cart import MAX_QTY_PER_LINE, Cart, price_tier_for
from ..context_processors import catalogue_nav, promoted_coupon
from ..forms import AccountForm, AddressForm, CheckoutForm, ContactForm, PasswordChangeForm, RegisterForm
from ..models import Address, Order, Product, WishlistItem, plain_number
from ..services import MpesaError, initiate_stk_push, mpesa_enabled
from ._common import form_errors, get_profile
from .auth import (
    REGISTER_ATTEMPT_LIMIT, REGISTER_LIMIT, REGISTER_WINDOW, RESET_LIMIT, RESET_WINDOW, SignInRefused, check_sign_in,
)
from .checkout import OrderRefused, after_order_placed, create_order
from .payments import payment_status
from .storefront import PAGE_SIZE, SORT_OPTIONS, _apply_sort

logger = logging.getLogger(__name__)

RAIL_SIZE = 10
# Promotional slides shown on the app's home screen (files in static/assets/slides/).
BANNERS = ['slide_two.webp', 'slide_three.webp', 'slide_four.webp', 'slide_five.webp']


def error(message, status=http.HTTP_400_BAD_REQUEST, errors=None):
    return Response({'error': message, 'errors': errors or {}}, status=status)


def money(value):
    return float(value) if value is not None else None


class MobileView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    @property
    def tier(self):
        return price_tier_for(self.request.user)

    def absolute(self, url):
        return self.request.build_absolute_uri(url) if url else None


class PublicView(MobileView):
    permission_classes = [AllowAny]


# ---------------------------------------------------------------------------
# Presenters
# ---------------------------------------------------------------------------
def product_json(view, product):
    tier = view.tier
    old = product.old_price_for(tier)
    return {
        'id': product.id,
        'item_code': product.item_code,
        'name': product.name,
        'description': product.description or '',
        'category': product.category.name if product.category else '',
        'category_slug': product.category.slug if product.category else '',
        'brand': product.brand.name if product.brand else '',
        'brand_slug': product.brand.slug if product.brand else '',
        'unit': product.pack_size,
        'price': money(product.price_for(tier)),
        'old_price': money(old),
        'discount': product.discount_percentage_for(tier),
        'price_tier': product.tier_used(tier),
        'vat_rate': plain_number(product.vat_rate),
        'purchasable': product.is_purchasable,
        'stock_state': product.stock_state,
        'stock_label': product.get_stock_state_display(),
        'available_stock': product.available_stock,
        'max_qty': MAX_QTY_PER_LINE if product.available_stock is None else min(MAX_QTY_PER_LINE, product.available_stock),
        # No photo: the app shows the brand's logo, or the initials on a tinted tile.
        'image_url': view.absolute(product.image.url) if product.has_image else None,
        'brand_logo_url': view.absolute(product.brand.logo_url) if product.brand else None,
        'initials': product.initials,
        'hue': product.placeholder_hue,
        'is_trending': product.is_trending,
        'is_best_seller': product.is_best_seller,
    }


def order_summary_json(order):
    return {
        'order_number': order.order_number,
        'status': order.status,
        'status_display': order.get_status_display(),
        'status_tone': order.status_tone,
        'payment_method': order.payment_method,
        'payment_method_display': order.get_payment_method_display(),
        'total': money(order.total_amount),
        'item_count': order.item_count,
        'is_paid': order.is_paid,
        'created_at': order.created_at.isoformat(),
    }


def order_json(view, order):
    payment = order.latest_payment
    data = order_summary_json(order)
    data.update({
        'full_name': order.full_name,
        'email': order.email,
        'phone': order.phone,
        'address': order.address,
        'city': order.city,
        'notes': order.notes or '',
        'subtotal': money(order.subtotal_amount),
        'discount': money(order.discount_amount),
        'coupon_code': order.coupon_code,
        'vat': money(order.vat_amount),
        'net': money(order.net_amount),
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
        'progress_step': order.progress_step,
        'can_pay': order.can_pay,
        'can_cancel': order.can_cancel,
        'needs_refund': order.needs_refund,
        'payment': {
            'state': payment.state,
            'receipt': payment.receipt_number,
            'description': payment.response_description or '',
        } if payment else None,
        'items': [{
            'product_id': item.product_id,
            'name': item.product.name,
            'unit': item.product.pack_size,
            'image_url': view.absolute(item.product.image.url) if item.product.has_image else None,
            'brand_logo_url': view.absolute(item.product.brand.logo_url) if item.product.brand else None,
            'initials': item.product.initials,
            'hue': item.product.placeholder_hue,
            'quantity': item.quantity,
            'price': money(item.price_at_purchase),
            'total': money(item.line_total),
        } for item in order.items.all()],
    })
    return data


def address_json(address):
    return {
        'id': address.id,
        'label': address.label,
        'physical_address': address.physical_address,
        'city': address.city,
        'is_primary': address.is_primary,
    }


def user_json(user):
    profile = get_profile(user)
    orders = profile.orders.all()
    return {
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'business_name': profile.business_name or '',
        'phone_number': profile.phone_number,
        'tax_id': profile.tax_id or '',
        'tier': profile.price_tier,
        'tier_label': profile.tier_label,
        'stats': {
            'orders': orders.count(),
            'open_orders': orders.filter(status__in=[Order.STATUS_PENDING, Order.STATUS_PAID, Order.STATUS_SHIPPED]).count(),
            'total_spent': money(orders.filter(paid_at__isnull=False).exclude(status=Order.STATUS_CANCELLED)
                                 .aggregate(total=Sum('total_amount'))['total'] or 0),
            'wishlist': WishlistItem.objects.filter(user=user).count(),
        },
    }


def coupon_json(coupon):
    if not coupon:
        return None
    return {'code': coupon.code, 'percent': plain_number(coupon.percent),
            'valid_until': coupon.valid_until.isoformat() if coupon.valid_until else None}


# ---------------------------------------------------------------------------
# Cart built from the app's lines
# ---------------------------------------------------------------------------
class _Basket(dict):
    """Stands in for the session ``Cart`` reads, holding the lines the app sent."""
    modified = False


def parse_lines(raw):
    """``[{"product_id": 1, "qty": 2}, ...]`` -> ``{"1": 2}``, ignoring anything malformed."""
    lines = {}
    if not isinstance(raw, list):
        return lines
    for entry in raw[:200]:
        if not isinstance(entry, dict):
            continue
        try:
            product_id, qty = int(entry.get('product_id')), int(entry.get('qty'))
        except (TypeError, ValueError):
            continue
        if product_id > 0 and qty > 0:
            lines[str(product_id)] = min(lines.get(str(product_id), 0) + qty, MAX_QTY_PER_LINE)
    return lines


def app_cart(request, data):
    """A ``Cart`` over the lines and coupon in the request body, priced for the signed-in user."""
    basket = _Basket({settings.CART_SESSION_ID: parse_lines(data.get('items'))})
    code = (data.get('coupon') or '').strip()
    if code:
        basket[settings.COUPON_SESSION_ID] = code
    return Cart(SimpleNamespace(session=basket, user=request.user))


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class ConfigView(PublicView):
    def get(self, request):
        site = settings.SITE_INFO
        return Response({
            'site': {key: site[key] for key in ('name', 'legal_name', 'tagline', 'phone', 'whatsapp', 'email',
                                                'address', 'po_box', 'hours', 'free_delivery_threshold')},
            'website_url': request.build_absolute_uri('/'),
            'mpesa_enabled': mpesa_enabled(),
            'sort_options': [{'value': value, 'label': label} for value, label in SORT_OPTIONS],
            'inquiry_types': [{'value': value, 'label': label} for value, label in ContactForm.base_fields['inquiry_type'].choices if value],
        })


def _category_json(view, category):
    return {'id': category.id, 'name': category.name, 'slug': category.slug,
            'image_url': view.absolute(category.image_url), 'product_count': getattr(category, 'product_count', None)}


def _brand_json(view, brand):
    return {'id': brand.id, 'name': brand.name, 'slug': brand.slug,
            'logo_url': view.absolute(brand.logo_url), 'product_count': getattr(brand, 'product_count', None)}


class HomeView(PublicView):
    def get(self, request):
        active = Product.objects.active().with_relations().with_stock()
        nav = catalogue_nav()
        return Response({
            'tier': self.tier,
            'banners': [self.absolute(f"{settings.STATIC_URL}assets/slides/{name}") for name in BANNERS],
            'promo_coupon': coupon_json(promoted_coupon()),
            'categories': [_category_json(self, c) for c in nav['categories'][:12]],
            'offers': [product_json(self, p) for p in active.on_offer(self.tier).order_by('-is_best_seller', 'name')[:RAIL_SIZE]],
            'best_sellers': [product_json(self, p) for p in active.filter(is_best_seller=True).order_by('name')[:RAIL_SIZE]],
            'trending': [product_json(self, p) for p in
                         active.order_by('-is_trending', '-is_best_seller', '-created_at')[:RAIL_SIZE]],
        })


class CategoryListView(PublicView):
    def get(self, request):
        return Response([_category_json(self, c) for c in catalogue_nav()['categories']])


class BrandListView(PublicView):
    def get(self, request):
        return Response([_brand_json(self, b) for b in catalogue_nav()['brands']])


class ProductPagination(PageNumberPagination):
    page_size = PAGE_SIZE


class ProductListView(PublicView):
    """``?q=&category=&brand=&sort=&collection=offers|best_sellers|trending|wholesale&page=``"""

    def get(self, request):
        params = request.query_params
        qs = Product.objects.active().with_relations().with_stock()
        collection = params.get('collection')
        if collection == 'offers':
            qs = qs.on_offer(self.tier)
        elif collection == 'best_sellers':
            qs = qs.filter(is_best_seller=True)
        elif collection == 'trending':
            qs = qs.filter(is_trending=True)
        elif collection == 'wholesale':
            qs = qs.with_wholesale_price()
        q = (params.get('q') or '').strip()[:100]
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(item_code__icontains=q)
                           | Q(brand__name__icontains=q) | Q(category__name__icontains=q))
        if params.get('category'):
            qs = qs.filter(category__slug=params['category'])
        if params.get('brand'):
            qs = qs.filter(brand__slug=params['brand'])
        sort = params.get('sort') if params.get('sort') in dict(SORT_OPTIONS) else 'featured'
        qs = _apply_sort(qs, sort, self.tier)

        paginator = ProductPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([product_json(self, p) for p in page])


class ProductDetailView(PublicView):
    def get(self, request, pk):
        active = Product.objects.active().with_relations().with_stock()
        product = get_object_or_404(active, pk=pk)
        related = active.filter(category=product.category).exclude(pk=product.pk) \
            .order_by('-is_best_seller', '-is_trending', 'name')[:8] if product.category else []
        data = product_json(self, product)
        data['related'] = [product_json(self, p) for p in related]
        data['in_wishlist'] = request.user.is_authenticated and \
            WishlistItem.objects.filter(user=request.user, product=product).exists()
        return Response(data)


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class CartQuoteView(PublicView):
    """Price the app's cart: ``{"items": [{"product_id", "qty"}], "coupon": "CODE"}``."""

    def post(self, request):
        sent = parse_lines(request.data.get('items'))
        cart = app_cart(request, request.data)
        lines = list(cart)
        code = (request.data.get('coupon') or '').strip()
        coupon_error = ''
        if code and cart.coupon is None:
            coupon_error = f'"{code[:30]}" is not a valid coupon code, or it has expired.'
        return Response({
            'tier': cart.tier,
            'lines': [{
                'product': product_json(self, item['product']),
                'qty': item['qty'],
                'price': money(item['price']),
                'total': money(item['total_price']),
            } for item in lines],
            # Products that were deactivated or removed since they were added on the phone.
            'removed': [int(pk) for pk in sent if pk not in cart.cart],
            'problems': cart.stock_problems(),
            'coupon': coupon_json(cart.coupon),
            'coupon_error': coupon_error,
            'subtotal': money(cart.subtotal),
            'discount': money(cart.discount),
            'vat': money(cart.vat),
            'net': money(cart.net),
            'total': money(cart.total),
            'free_delivery_threshold': settings.SITE_INFO['free_delivery_threshold'],
        })


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _signed_in(user, status=http.HTTP_200_OK):
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'user': user_json(user)}, status=status)


class LoginView(PublicView):
    authentication_classes = []

    def post(self, request):
        try:
            user = check_sign_in(request, request.data.get('username'), request.data.get('password'))
        except SignInRefused as exc:
            return error(str(exc), status=exc.status)
        return _signed_in(user)


class RegisterView(PublicView):
    authentication_classes = []

    def post(self, request):
        form = RegisterForm(request.data)
        address = throttle.client_ip(request)
        if not throttle.hit(f'register-attempts:{address}', REGISTER_ATTEMPT_LIMIT, REGISTER_WINDOW):
            return error("Too many sign-up attempts from your connection. Please try again in an hour.", status=429)
        if not form.is_valid():
            return error("Please fix the highlighted fields.", errors=form_errors(form))
        if not throttle.hit(f'register:{address}', REGISTER_LIMIT, REGISTER_WINDOW):
            return error("Too many accounts have been created from your connection. Please try again in an hour.",
                         status=429)
        return _signed_in(form.save(), status=http.HTTP_201_CREATED)


class LogoutView(MobileView):
    def post(self, request):
        # One token per account: signing out on the phone signs the app out everywhere.
        Token.objects.filter(user=request.user).delete()
        return Response({'ok': True})


class PasswordResetView(PublicView):
    authentication_classes = []

    def post(self, request):
        form = PasswordResetForm(request.data)
        if not form.is_valid():
            return error("Enter a valid email address.", errors=form_errors(form))
        if not throttle.hit(f'password-reset:{throttle.client_ip(request)}', RESET_LIMIT, RESET_WINDOW):
            return error("Too many reset emails have been requested. Please wait an hour and try again.", status=429)
        form.save(
            request=request,
            use_https=request.is_secure(),
            email_template_name='core/auth/password_reset_email.html',
            subject_template_name='core/auth/password_reset_subject.txt',
        )
        # Same answer whether or not the address has an account.
        return Response({'message': "If that email has an account, we've sent a link to reset the password."})


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
class MeView(MobileView):
    def get(self, request):
        return Response(user_json(request.user))

    def patch(self, request):
        user, profile = request.user, get_profile(request.user)
        current = {
            'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
            'business_name': profile.business_name or '', 'phone_number': profile.phone_number,
            'tax_id': profile.tax_id or '',
        }
        current.update({key: value for key, value in request.data.items() if key in current})
        form = AccountForm(user, current)
        if not form.is_valid():
            return error("Please check the highlighted fields.", errors=form_errors(form))
        data = form.cleaned_data
        user.first_name, user.last_name, user.email = data['first_name'], data['last_name'], data['email']
        user.save()
        profile.business_name = data.get('business_name') or None
        profile.phone_number = data['phone_number']
        profile.tax_id = data.get('tax_id')
        profile.contact_person = user.get_full_name()
        profile.save()
        return Response(user_json(user))


class PasswordChangeView(MobileView):
    def post(self, request):
        form = PasswordChangeForm(request.user, request.data)
        if not form.is_valid():
            return error("Please check the password fields.", errors=form_errors(form))
        request.user.set_password(form.cleaned_data['new_password'])
        request.user.save()
        # A new token: any other phone signed in with the old password is signed out.
        Token.objects.filter(user=request.user).delete()
        return _signed_in(request.user)


class AddressListView(MobileView):
    def get(self, request):
        return Response([address_json(a) for a in get_profile(request.user).addresses.all()])

    def post(self, request):
        return _save_address(request, None)


class AddressDetailView(MobileView):
    def patch(self, request, pk):
        return _save_address(request, get_object_or_404(Address, pk=pk, customer=get_profile(request.user)))

    def delete(self, request, pk):
        profile = get_profile(request.user)
        address = get_object_or_404(Address, pk=pk, customer=profile)
        was_primary = address.is_primary
        address.delete()
        if was_primary:
            remaining = profile.addresses.first()
            if remaining:
                remaining.is_primary = True
                remaining.save()
        return Response([address_json(a) for a in profile.addresses.all()])


def _save_address(request, instance):
    profile = get_profile(request.user)
    data = {'label': '', 'physical_address': '', 'city': '', 'is_primary': False}
    if instance is not None:
        data.update(address_json(instance))
    data.update({key: value for key, value in request.data.items() if key in data})
    data['label'] = (data['label'] or '').strip() or 'Delivery Address'
    data['city'] = (data['city'] or '').strip() or 'Nairobi'
    form = AddressForm(data, instance=instance)
    if not form.is_valid():
        return error("Please check the address.", errors=form_errors(form))
    address = form.save(commit=False)
    address.customer = profile
    if not profile.addresses.exclude(pk=address.pk).exists():
        address.is_primary = True
    address.save()
    return Response([address_json(a) for a in profile.addresses.all()],
                    status=http.HTTP_200_OK if instance else http.HTTP_201_CREATED)


class WishlistView(MobileView):
    def get(self, request):
        ids = list(WishlistItem.objects.filter(user=request.user, product__is_active=True).values_list('product_id', flat=True))
        products = Product.objects.filter(id__in=ids).with_relations().with_stock().in_bulk()
        return Response([product_json(self, products[pk]) for pk in ids if pk in products])


class WishlistToggleView(MobileView):
    def post(self, request):
        try:
            product_id = int(request.data.get('product_id'))
        except (TypeError, ValueError):
            return error("Invalid product.")
        product = get_object_or_404(Product, id=product_id, is_active=True)
        item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
        if not created:
            item.delete()
        return Response({'added': created, 'ids': list(WishlistItem.objects.filter(user=request.user)
                                                       .values_list('product_id', flat=True))})


# ---------------------------------------------------------------------------
# Orders & payments
# ---------------------------------------------------------------------------
def _orders(user):
    return Order.objects.filter(customer__user=user).prefetch_related(
        'items__product__unit_of_measure', 'items__product__category', 'items__product__brand', 'mpesa_payments')


class OrderPagination(PageNumberPagination):
    page_size = 15


class OrderListView(MobileView):
    def get(self, request):
        qs = _orders(request.user)
        if request.query_params.get('status') in dict(Order.STATUS_CHOICES):
            qs = qs.filter(status=request.query_params['status'])
        paginator = OrderPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([order_summary_json(o) for o in page])

    def post(self, request):
        """Place an order: the cart lines and coupon, plus the checkout form fields."""
        form = CheckoutForm(request.data)
        if not form.is_valid():
            return error("Please check the highlighted fields.", errors=form_errors(form))
        data = form.cleaned_data
        try:
            order, _ = create_order(get_profile(request.user), data, lambda: app_cart(request, request.data))
        except OrderRefused as exc:
            return error(str(exc), status=exc.status)
        payment = after_order_placed(order, data)
        return Response({'order': order_json(self, _orders(request.user).get(pk=order.pk)), 'payment': payment},
                        status=http.HTTP_201_CREATED)


class OrderDetailView(MobileView):
    def get(self, request, order_number):
        return Response(order_json(self, get_object_or_404(_orders(request.user), order_number=order_number)))


class OrderActionView(MobileView):
    """POST /orders/<number>/<action>/ with action cancel, pay or pay-on-delivery."""

    def post(self, request, order_number, action):
        order = get_object_or_404(_orders(request.user), order_number=order_number)
        message = ''
        if action == 'cancel':
            if not order.can_cancel:
                return error("This order can no longer be cancelled. Please contact support.")
            order.status = Order.STATUS_CANCELLED
            order.save()  # the stock it was holding is released by the status-change signal
            message = f"Order {order.order_number} has been cancelled."
        elif action == 'pay':
            if not order.can_pay:
                return error(f"This order is {order.get_status_display().lower()} and can no longer be paid.")
            try:
                initiate_stk_push(order, request.data.get('phone') or order.phone)
            except MpesaError as exc:
                return error(str(exc), status=http.HTTP_502_BAD_GATEWAY)
            message = "Check your phone and enter your M-Pesa PIN."
        elif action == 'pay-on-delivery':
            if not order.can_pay:
                return error("This order's payment method can no longer be changed. Please contact support.")
            order.payment_method = Order.PAYMENT_COD
            order.status = Order.STATUS_PENDING  # a failed prompt no longer matters
            order.save()
            message = f"Order {order.order_number} will be paid on delivery. Have KSh {order.total_amount:,.0f} ready for the driver."
        else:
            return error("Unknown action.", status=http.HTTP_404_NOT_FOUND)
        order = _orders(request.user).get(pk=order.pk)
        return Response({'message': message, 'order': order_json(self, order)})


class PaymentStatusView(MobileView):
    def get(self, request, order_number):
        order = get_object_or_404(_orders(request.user), order_number=order_number)
        return Response(payment_status(order))


# ---------------------------------------------------------------------------
# Help desk
# ---------------------------------------------------------------------------
CONTACT_LIMIT, CONTACT_WINDOW = 10, 60 * 60


class ContactView(PublicView):
    def post(self, request):
        form = ContactForm(request.data)
        if not form.is_valid():
            return error("Please check the highlighted fields.", errors=form_errors(form))
        if not throttle.hit(f'contact:{throttle.client_ip(request)}', CONTACT_LIMIT, CONTACT_WINDOW):
            return error("Too many messages from your connection. Please call or WhatsApp us instead.", status=429)
        message = form.save()
        try:
            send_mail(
                f"[Mahitaji app] {message.get_inquiry_type_display()} from {message.full_name}",
                f"{message.message}\n\nFrom: {message.full_name} <{message.email}> {message.phone}\nBusiness: {message.business_name}",
                settings.DEFAULT_FROM_EMAIL, [settings.SITE_INFO['email']], fail_silently=True,
            )
        except Exception:
            logger.exception("Contact email failed")
        return Response({'message': "Thanks! Our team will get back to you within one business day."},
                        status=http.HTTP_201_CREATED)

