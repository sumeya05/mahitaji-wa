from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Category, Brand, Supplier, UnitOfMeasure, Product, StockLedger, 
    CustomerProfile, Address, Order, OrderItem, MpesaTransaction
)
from import_export.admin import ImportExportModelAdmin
from .resources import ProductResource, SupplierResource, CategoryResource, BrandResource, StockLedgerResource


# 1. Inline for Order Items
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['product', 'quantity', 'price_at_purchase']

# 2. Brand Admin
@admin.register(Brand)
class BrandAdmin(ImportExportModelAdmin):
    resource_class = BrandResource
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']

# 3. Product Admin
@admin.register(Product)
class ProductAdmin(ImportExportModelAdmin): # Inherit from ImportExportModelAdmin
    resource_class = ProductResource
    
    # Keep your full list_display to see all important info at a glance
    list_display = [
        'item_code', 'name',
        'unit_of_measure', 'old_price','retail_price', 'wholesale_price', 
        'current_stock', 'is_trending','is_best_seller', 'is_active'
    ]
    
    # Keep your readonly fields so the stock property doesn't crash the edit page
    readonly_fields = ['current_stock']
    
    # Keep these for better usability
    list_filter = ['category', 'brand', 'unit_of_measure', 'supplier', 'is_active']
    search_fields = ['name', 'item_code']
    prepopulated_fields = {'slug': ('name',)}
    
    # Keep this so you can change prices quickly without opening every product
    list_editable = ['is_active']

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
class StockLedgerAdmin(ImportExportModelAdmin):
    resource_class = StockLedgerResource
    # We display 'quantity' directly, but label the column clearly
    list_display = ['product', 'quantity_in_pcs', 'transaction_type', 'timestamp', 'reference_number']

    def quantity_in_pcs(self, obj):
        # We hard-code 'pcs' here because the Ledger is the 'Base Unit' zone
        return f"{obj.quantity} pcs"
    
    quantity_in_pcs.short_description = 'Qty (Base Units)'


    
# 8. Simple registrations for remaining models
@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    resource_class = CategoryResource
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']



# 9. Supplier Admin
@admin.register(Supplier)
class SupplierAdmin(ImportExportModelAdmin): # Use ImportExportModelAdmin
    resource_class = SupplierResource
    list_display = ['name', 'erp_id', 'contact_person', 'phone_number']
    search_fields = ['name', 'erp_id', 'contact_person']


admin.site.register(Address)














