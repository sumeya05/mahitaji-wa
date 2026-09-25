from django.contrib import admin
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin

from .models import (
    Address, Brand, Category, ContactMessage, CustomerProfile, MpesaTransaction,
    NewsletterSubscriber, Order, OrderItem, Product, StockLedger, Supplier,
    UnitOfMeasure, WishlistItem,
)
from .resources import BrandResource, CategoryResource, ProductResource, StockLedgerResource, SupplierResource

admin.site.site_header = "Mahitaji Administration"
admin.site.site_title = "Mahitaji Admin"
admin.site.index_title = "Store management"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['product', 'quantity', 'price_at_purchase', 'subtotal']
    readonly_fields = ['subtotal']
    autocomplete_fields = ['product']


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


@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin):
    resource_class = ProductResource
    list_display = [
        'item_code', 'name', 'brand', 'category', 'unit_of_measure',
        'old_price', 'retail_price', 'old_wholesale_price', 'wholesale_price', 'stock_level',
        'is_trending', 'is_best_seller', 'is_active', 'thumbnail',
    ]
    readonly_fields = ['stock_level', 'created_at', 'last_sync_time']
    list_filter = ['category', 'brand', 'unit_of_measure', 'supplier', 'is_active', 'is_trending', 'is_best_seller']
    search_fields = ['name', 'item_code', 'brand__name']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'is_trending', 'is_best_seller']
    list_per_page = 50
    autocomplete_fields = ['category', 'brand', 'supplier']

    @admin.display(description='Stock')
    def stock_level(self, obj):
        return obj.current_stock

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
    list_display = ['order_number', 'customer', 'full_name', 'payment_method', 'status', 'total_amount', 'synced_to_erp', 'created_at']
    list_filter = ['status', 'payment_method', 'synced_to_erp', 'created_at']
    search_fields = ['order_number', 'full_name', 'phone', 'customer__user__username', 'customer__business_name', 'erp_reference']
    inlines = [OrderItemInline]
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    actions = ['mark_paid', 'mark_shipped', 'mark_delivered', 'mark_cancelled', 'sync_with_focus_erp']

    def _set_status(self, request, queryset, status):
        count = 0
        for order in queryset:
            order.status = status
            order.save()
            count += 1
        self.message_user(request, f"{count} order(s) marked as {status.title()}.")

    @admin.action(description="Mark selected as Paid")
    def mark_paid(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_PAID)

    @admin.action(description="Mark selected as Shipped")
    def mark_shipped(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_SHIPPED)

    @admin.action(description="Mark selected as Delivered")
    def mark_delivered(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_DELIVERED)

    @admin.action(description="Mark selected as Cancelled")
    def mark_cancelled(self, request, queryset):
        self._set_status(request, queryset, Order.STATUS_CANCELLED)

    @admin.action(description="Push selected orders to Focus ERP")
    def sync_with_focus_erp(self, request, queryset):
        self.message_user(request, f"Initiating sync for {queryset.count()} orders to Focus ERP...")


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'business_name', 'phone_number', 'tax_id', 'is_wholesaler', 'erp_id']
    list_filter = ['is_wholesaler']
    list_editable = ['is_wholesaler']
    search_fields = ['user__username', 'user__email', 'business_name', 'phone_number', 'erp_id']
    inlines = [AddressInline]


@admin.register(MpesaTransaction)
class MpesaAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'order', 'amount', 'phone_number', 'is_success', 'transaction_date', 'created_at']
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

    @admin.display(description='Qty (base units)')
    def quantity_in_pcs(self, obj):
        return f"{obj.quantity} pcs"


@admin.register(Supplier)
class SupplierAdmin(ImportExportModelAdmin):
    resource_class = SupplierResource
    list_display = ['name', 'erp_id', 'contact_person', 'phone_number']
    search_fields = ['name', 'erp_id', 'contact_person']


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ['customer', 'label', 'city', 'is_primary']
    search_fields = ['customer__user__username', 'physical_address', 'city']


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
