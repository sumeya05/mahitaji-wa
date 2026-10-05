"""
Customer account area: dashboard, order history, addresses, payment details, profile settings and wishlist.
"""
import logging

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from ..forms import (
    AccountForm, AddressForm, PasswordChangeForm, normalize_phone,
)
from ..models import (
    Address, MpesaTransaction, Order, Product, WishlistItem,
)
from ._common import form_errors, get_profile, is_ajax, json_error, json_ok, request_data

logger = logging.getLogger(__name__)


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
        'total_spent': orders.filter(paid_at__isnull=False).exclude(status=Order.STATUS_CANCELLED)
                             .aggregate(total=Sum('total_amount'))['total'] or 0,
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
    items = list(WishlistItem.objects.filter(user=request.user, product__is_active=True))
    # One query for the products, with the stock figures the product card shows.
    products = Product.objects.filter(id__in=[item.product_id for item in items]).with_relations().with_stock().in_bulk()
    for item in items:
        item.product = products[item.product_id]
    ctx['items'] = items
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
