from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

# --- 1. PRODUCT & INVENTORY MODELS ---

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)

    class Meta:
        verbose_name_plural = "Categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    sku = models.CharField(max_length=50, unique=True) # Focus ERP item code
    description = models.TextField()
    
    # Dual Pricing Logic
    retail_price = models.DecimalField(max_digits=12, decimal_places=2)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2)
    min_wholesale_qty = models.PositiveIntegerField(default=10)
    
    # Inventory Management
    stock_qty = models.IntegerField(default=0)
    unit_of_measure = models.CharField(max_length=20, default="pcs") # e.g., kg, bale, box
    image = models.ImageField(upload_to='products/')
    is_active = models.BooleanField(default=True)
    
    # Focus ERP Sync Info
    focus_item_id = models.CharField(max_length=100, null=True, blank=True)
    last_sync_time = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} - {self.name}"


# --- 2. USER & CUSTOMER MODELS ---

class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=15)
    is_wholesaler = models.BooleanField(default=False)
    
    # Unique ID for Focus ERP customer record
    focus_erp_id = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        role = "Wholesaler" if self.is_wholesaler else "Retailer"
        return f"{self.user.get_full_name()} ({role})"

class Address(models.Model):
    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=50) # e.g. Office, Home, Warehouse
    physical_address = models.TextField()
    city = models.CharField(max_length=100, default="Nairobi")
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Addresses"

    def __str__(self):
        return f"{self.label} - {self.customer.user.username}"


# --- 3. ORDER & TRANSACTION MODELS ---

class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Payment'),
        ('PAID', 'Processing'),
        ('SHIPPED', 'In Transit'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]

    order_number = models.CharField(max_length=50, unique=True) # e.g. ORD-2026-001
    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='orders')
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Sync status for Focus ERP integration
    synced_to_erp = models.BooleanField(default=False)
    erp_reference = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"Order {self.order_number}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    # Captured at time of sale to ensure historical accuracy
    price_at_purchase = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"


# --- 4. PAYMENT (M-PESA) MODELS ---

class MpesaTransaction(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='mpesa_payment')
    checkout_request_id = models.CharField(max_length=100, unique=True) 
    merchant_request_id = models.CharField(max_length=100)
    
    # Callback Data
    receipt_number = models.CharField(max_length=50, null=True, blank=True) # e.g. RBT123X456
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15)
    transaction_date = models.DateTimeField(null=True, blank=True)
    
    is_success = models.BooleanField(default=False)
    response_description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"M-Pesa {self.receipt_number or self.checkout_request_id}"