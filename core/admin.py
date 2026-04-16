from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Category, Brand, UnitOfMeasure, Product, StockLedger, 
    CustomerProfile, Address, Order, OrderItem, MpesaTransaction
)

# 1. Inline for Order Items
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['product', 'quantity', 'price_at_purchase']

# 2. Brand Admin
@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['brand_logo', 'name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']

    def brand_logo(self, obj):
        if obj.logo:
            return format_html('<img src="{}" style="width: 45px; height: auto; border-radius: 4px;" />', obj.logo.url)
        return "No Logo"
    brand_logo.short_description = 'Logo'

# 3. Product Admin
# 3. Product Admin
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    # Change 'stock_qty' to 'current_stock'
    list_display = ['sku', 'name', 'brand', 'unit_of_measure', 'retail_price', 'wholesale_price', 'current_stock', 'is_active']
    
    # Add 'current_stock' to readonly_fields since it's a calculated property
    readonly_fields = ['current_stock']
    
    list_filter = ['category', 'brand', 'unit_of_measure', 'is_active']
    search_fields = ['name', 'sku', 'focus_item_id']
    prepopulated_fields = {'slug': ('name',)}
    
    # REMOVED 'stock_qty' from list_editable because it's no longer a direct database field
    list_editable = ['retail_price', 'wholesale_price', 'is_active']

    # This makes the property look nice in the admin list
    def current_stock(self, obj):
        return obj.current_stock
    current_stock.short_description = 'Stock Level'

# 4. UOMs
@admin.register(UnitOfMeasure)
class UOMAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'is_base_unit', 'conversion_display']
    list_filter = ['is_base_unit']
    
    def conversion_display(self, obj):
        if obj.is_base_unit:
            return "---"
        if obj.base_unit:
            return f"1 {obj.short_name} = {obj.conversion_factor} {obj.base_unit.short_name}"
        return "No base unit set"
    conversion_display.short_description = 'Conversion Logic'

# 5. Order Admin
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'customer', 'status', 'total_amount', 'synced_to_erp', 'created_at']
    list_filter = ['status', 'synced_to_erp', 'created_at']
    search_fields = ['order_number', 'customer__user__username', 'erp_reference']
    inlines = [OrderItemInline]
    actions = ['sync_with_focus_erp']

    def sync_with_focus_erp(self, request, queryset):
        count = queryset.count()
        self.message_user(request, f"Initiating sync for {count} orders to Focus ERP...")
    sync_with_focus_erp.short_description = "Push selected orders to Focus ERP"

# 6. Customer Profile Admin
@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone_number', 'is_wholesaler', 'focus_erp_id']
    list_filter = ['is_wholesaler']
    search_fields = ['user__username', 'phone_number', 'focus_erp_id']

# 7. Payment Monitoring
@admin.register(MpesaTransaction)
class MpesaAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'order', 'amount', 'phone_number', 'is_success', 'transaction_date']
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False

# 8. 
@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'product', 'transaction_type', 'input_quantity', 'transaction_uom', 'quantity']
    list_filter = ['transaction_type', 'timestamp']
    search_fields = ['product__name', 'reference_number']
    
    # This prevents editing old ledger entries to keep your audit trail clean
    def has_change_permission(self, request, obj=None):
        return False
    
# 8. Simple registrations for remaining models
admin.site.register(Category)
admin.site.register(Address)
















