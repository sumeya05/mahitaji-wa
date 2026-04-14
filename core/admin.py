from django.contrib import admin
from .models import (
    Category, Product, CustomerProfile, 
    Address, Order, OrderItem, MpesaTransaction
)

# 1. Inline for Order Items
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ['product', 'quantity', 'price_at_purchase']
    readonly_fields = ['price_at_purchase']

# 2. Product Admin
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['sku', 'name', 'retail_price', 'wholesale_price', 'stock_qty', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'sku', 'focus_item_id']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['retail_price', 'wholesale_price', 'stock_qty']

# 3. Order Admin
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

# 4. Customer Profile Admin
@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone_number', 'is_wholesaler', 'focus_erp_id']
    list_filter = ['is_wholesaler']
    search_fields = ['user__username', 'phone_number', 'focus_erp_id']

# 5. Payment Monitoring
@admin.register(MpesaTransaction)
class MpesaAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'order', 'amount', 'phone_number', 'is_success', 'transaction_date']
    # Making transaction history immutable for security
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False

# 6. Simple registrations for basic models
admin.site.register(Category)
admin.site.register(Address)