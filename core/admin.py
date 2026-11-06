from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin

from . import images

from .models import (
    ChatMessage,
    Address, Brand, Category, ContactMessage, Coupon, CustomerProfile, MpesaTransaction,
    NewsletterSubscriber, Order, OrderItem, Product, StockLedger, Supplier,
    UnitOfMeasure, WishlistItem,
)
from .resources import (
    BrandResource, CategoryResource, CustomerResource, ProductResource, StockLedgerResource, SupplierResource,
)
from .services import sync_order_stock

admin.site.site_header = "Mahitaji Administration"
admin.site.site_title = "Mahitaji Admin"
admin.site.index_title = "Store management"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['product', 'quantity', 'price_at_purchase', 'subtotal']
    readonly_fields = ['subtotal']
    autocomplete_fields = ['product']


class PaymentInline(admin.TabularInline):
    """Every M-Pesa prompt sent for the order (read-only)."""
    model = MpesaTransaction
    extra = 0
    can_delete = False
    fields = ['created_at', 'phone_number', 'amount', 'receipt_number', 'is_success', 'response_description']
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(Brand)
class BrandAdmin(ImportExportModelAdmin):
    resource_class = BrandResource
    list_display = ['name', 'slug', 'product_count']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']

    def product_count(self, obj):
        return obj.products.count()


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    resource_class = CategoryResource
    list_display = ['name', 'slug', 'product_count']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']

    def product_count(self, obj):
        return obj.products.count()


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp,.gif,.zip'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        return [single(item, initial) for item in (data if isinstance(data, (list, tuple)) else [data])]


class ProductImageUploadForm(forms.Form):
    files = MultipleFileField(label="Image files or .zip archives")
    replace_existing = forms.BooleanField(
        label="Replace photos products already have", required=False, initial=True,
        help_text="Untick to only fill in products that have no photo yet.",
    )


@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin):
    resource_class = ProductResource
    change_list_template = 'admin/core/product/change_list.html'
    list_display = [
        'item_code', 'name', 'brand', 'category', 'unit_of_measure',
        'old_retail_price', 'retail_price', 'old_wholesale_price', 'wholesale_price', 'vat_rate', 'stock_level',
        'is_trending', 'is_best_seller', 'is_active', 'thumbnail',
    ]
    readonly_fields = ['stock_level', 'created_at', 'last_sync_time']
    list_filter = ['category', 'brand', 'unit_of_measure', 'supplier', 'is_active', 'is_trending', 'is_best_seller']
    search_fields = ['name', 'item_code', 'brand__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'is_trending', 'is_best_seller']
    list_per_page = 50
    autocomplete_fields = ['category', 'brand', 'supplier']

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock()  # stock column without a query per row

    def get_urls(self):
        return [
            path('upload-images/', self.admin_site.admin_view(self.upload_images_view), name='core_product_upload_images'),
        ] + super().get_urls()

    def upload_images_view(self, request):
        """Bulk photo upload: files named after item codes are attached to those products."""
        if not self.has_change_permission(request):
            raise PermissionDenied
        report = None
        form = ProductImageUploadForm(request.POST or None, request.FILES or None)
        if request.method == 'POST' and form.is_valid():
            report = images.attach(form.cleaned_data['files'], replace_existing=form.cleaned_data['replace_existing'])
            linked = len(report['linked'])
            if linked:
                messages.success(request, f"{linked} product photo{'s' if linked != 1 else ''} attached.")
            if report['errors']:
                messages.warning(request, f"{len(report['errors'])} file(s) could not be used; see below.")
            form = ProductImageUploadForm()
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta, 'title': "Upload product images", 'form': form, 'report': report,
            'media_folder': f"{settings.MEDIA_ROOT}/products/",
        }
        return render(request, 'admin/core/product/upload_images.html', context)

    @admin.display(description='Stock')
    def stock_level(self, obj):
        if not obj.is_stock_tracked:
            return "not tracked"
        return f"{obj.current_stock} ({obj.get_stock_state_display()})"

    @admin.display(description='Image')
    def thumbnail(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:36px;border-radius:6px" alt="">', obj.image.url)
        return "—"


@admin.register(UnitOfMeasure)
class UOMAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'is_base_unit', 'conversion_display']
    list_filter = ['is_base_unit']

    @admin.display(description='Conversion')
    def conversion_display(self, obj):
        if obj.is_base_unit:
            return "base unit"
        if obj.base_unit:
            return f"1 {obj.short_name} = {obj.conversion_factor} {obj.base_unit.short_name}"
        return "No base unit set"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'customer', 'full_name', 'payment_method', 'status', 'payment_state',
                    'total_amount', 'coupon_code', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['order_number', 'full_name', 'phone', 'customer__user__username', 'customer__business_name',
                     'coupon_code', 'erp_reference']
    inlines = [OrderItemInline, PaymentInline]
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    actions = ['mark_paid', 'mark_shipped', 'mark_delivered', 'mark_cancelled']

    @admin.display(description='Payment')
    def payment_state(self, obj):
        if obj.needs_refund:
            return "PAID - REFUND DUE"
        return "Paid" if obj.is_paid else "Unpaid"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_order_stock(form.instance)  # lines may have been edited: keep the stock ledger in step

    def _set_status(self, request, queryset, status):
        count = 0
        for order in queryset:
            order.status = status
            order.save()
            count += 1
        self.message_user(request, f"{count} order(s) marked as {status.title()}.")

    @admin.action(description="Mark selected as Paid (payment received)")
    def mark_paid(self, request, queryset):
        count = 0
        for order in queryset:
            order.mark_paid()
            count += 1
        self.message_user(request, f"Payment recorded for {count} order(s).")

    @admin.action(description="Mark selected as Shipped")
    def mark_shipped(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_SHIPPED)

    @admin.action(description="Mark selected as Delivered")
    def mark_delivered(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_DELIVERED)

    @admin.action(description="Mark selected as Cancelled (releases their stock)")
    def mark_cancelled(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_CANCELLED)


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'percent', 'active', 'valid_until', 'promote']
    list_editable = ['active', 'promote']
    list_filter = ['active', 'promote']
    search_fields = ['code']


@admin.register(CustomerProfile)
class CustomerProfileAdmin(ImportExportModelAdmin):
    """The customer master: shop accounts and delivery customers added here without a login."""
    resource_class = CustomerResource
    list_display = ['customer_code', 'display_name', 'user', 'phone_number', 'area', 'route', 'tax_id',
                    'is_wholesaler', 'erp_id']
    list_filter = ['is_wholesaler', 'area__route', 'area']
    list_editable = ['is_wholesaler']
    list_select_related = ['user', 'area__route']
    search_fields = ['customer_code', 'user__username', 'user__email', 'business_name', 'contact_person',
                     'phone_number', 'erp_id']
    autocomplete_fields = ['area']
    fieldsets = [
        (None, {'fields': ['customer_code', 'business_name', 'contact_person', 'phone_number', 'user']}),
        ('Pricing and ERP', {'fields': ['is_wholesaler', 'tax_id', 'erp_id']}),
        ('Delivery', {'fields': ['area', 'latitude', 'longitude'],
                      'description': 'Area and GPS location used by Mahitaji Fleet. The route comes from the area.'}),
    ]
    inlines = [AddressInline]

    @admin.display(description='Name', ordering='business_name')
    def display_name(self, obj):
        return obj.display_name


@admin.register(MpesaTransaction)
class MpesaAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'order', 'amount', 'phone_number', 'state', 'transaction_date', 'created_at']
    list_filter = ['is_success']
    search_fields = ['receipt_number', 'checkout_request_id', 'order__order_number', 'phone_number']
    readonly_fields = [f.name for f in MpesaTransaction._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(StockLedger)
class StockLedgerAdmin(ImportExportModelAdmin):
    resource_class = StockLedgerResource
    list_display = ['product', 'quantity_in_pcs', 'transaction_type', 'timestamp', 'reference_number']
    list_filter = ['transaction_type']
    search_fields = ['product__name', 'product__item_code', 'reference_number']
    autocomplete_fields = ['product']

    @admin.display(description='Qty (unit of sale)', ordering='quantity')
    def quantity_in_pcs(self, obj):
        unit = obj.product.pack_size.lower() if obj.product_id and obj.product.pack_size else 'unit'
        return f"{obj.quantity:+d} {unit}"


@admin.register(Supplier)
class SupplierAdmin(ImportExportModelAdmin):
    resource_class = SupplierResource
    list_display = ['name', 'erp_id', 'contact_person', 'phone_number']
    search_fields = ['name', 'erp_id', 'contact_person']


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ['customer', 'label', 'city', 'is_primary']
    search_fields = ['customer__user__username', 'customer__business_name', 'customer__customer_code',
                     'physical_address', 'city']


@admin.register(WishlistItem)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'product', 'added_at']
    search_fields = ['user__username', 'product__name']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'business_name', 'email', 'inquiry_type', 'created_at', 'is_resolved']
    list_filter = ['inquiry_type', 'is_resolved']
    list_editable = ['is_resolved']
    search_fields = ['full_name', 'email', 'business_name', 'message']
    readonly_fields = ['created_at']


@admin.register(NewsletterSubscriber)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['email']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Read-only log of assistant conversations."""
    list_display = ['created_at', 'handled_by', 'user', 'short_message', 'short_reply']
    list_filter = ['handled_by', 'created_at']
    search_fields = ['message', 'reply', 'user__username', 'session_key']
    readonly_fields = ['user', 'session_key', 'message', 'reply', 'handled_by', 'product_ids', 'created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50

    @admin.display(description='Question')
    def short_message(self, obj):
        return obj.message[:80]

    @admin.display(description='Answer')
    def short_reply(self, obj):
        return obj.reply[:80]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
