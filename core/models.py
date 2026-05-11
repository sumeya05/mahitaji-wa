from django.db import models # type: ignore
from django.contrib.auth.models import User # type: ignore
from django.utils.text import slugify # type: ignore
from django.db.models import Sum # type: ignore





# --- A. USER & CUSTOMER MODELS ---
class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customerprofile')
    # Fields added to support business registration requirements
    business_name = models.CharField(max_length=255, blank=True, null=True) 
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=15)
    
    # New Tax ID field for KRA/eTIMS integration
    tax_id = models.CharField(max_length=15, null=True, blank=True, verbose_name="KRA PIN")
    
    is_wholesaler = models.BooleanField(default=False)
    focus_erp_id = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        role = "Wholesaler" if self.is_wholesaler else "Retailer"
        return f"{self.business_name} ({role})"


class Address(models.Model):
    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=50) 
    physical_address = models.TextField()
    city = models.CharField(max_length=100, default="Nairobi")
    is_primary = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Addresses"

    def __str__(self):
        return f"{self.label} - {self.customer.user.username}"
    










    
# --- B. PRODUCT & INVENTORY MODELS ---
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True) # Added unique=True
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    description = models.TextField(blank=True, null=True) # Useful for SEO later

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True) # Added unique=True
    slug = models.SlugField(unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    erp_id = models.CharField(max_length=50, blank=True, null=True, help_text="Supplier ID in Focus ERP")

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class UnitOfMeasure(models.Model):
    name = models.CharField(max_length=50, unique=True) # e.g., "Bale", "Piece"
    short_name = models.CharField(max_length=10, unique=True) # e.g., "bl", "pc"
    
    is_base_unit = models.BooleanField(default=False, help_text="Is this the smallest unit (e.g., Piece)?")
    base_unit = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversions')
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=2, default=1.0, help_text="How many base units are in this unit? (e.g., 1 Bale = 12 Pieces)")

    class Meta:
        verbose_name = "Unit of Measure"
        verbose_name_plural = "Units of Measure"

    def __str__(self):
        return self.short_name
    
class Product(models.Model):

    item_code = models.CharField(max_length=50, unique=True, null=True, help_text="Focus ERP item code")
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True) 
    description = models.TextField(blank=True, null=True)   
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    supplier = models.ForeignKey(
        Supplier, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='products'
    )
    unit_of_measure = models.ForeignKey(UnitOfMeasure, on_delete=models.SET_NULL, null=True, related_name='products')
    old_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2)
    average_rating = models.PositiveIntegerField(default=4)      
    image = models.ImageField(upload_to='products/', null=True, blank=True) 
    last_sync_time = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)    


    is_trending = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    

    @property
    def discount_percentage(self):
        if self.old_price and self.old_price > self.retail_price:
            discount = ((self.old_price - self.retail_price) / self.old_price) * 100
            return f"-{int(discount)}%"
        return None
    
    @property
    def amount_saved(self):
        if self.old_price and self.old_price > self.retail_price:
            return self.old_price - self.retail_price
        return 0
    
    @property
    def current_stock(self):
        """Calculates current stock level in base units from ledger."""
        total = self.stock_ledger.aggregate(total=Sum('quantity'))['total']
        return total or 0
    
    @property
    def image_url(self):
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        # Return a link to a default "no-image" icon in your static folder
        return "/static/assets/images/placeholder.jpg"

    def save(self, *args, **kwargs):
        if not self.slug: self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_code} - {self.name}"   
       

    # --- Properties to match your template logic ---
    @property
    def has_discount(self):
        return self.old_price is not None and self.old_price > self.retail_price
    







class StockLedger(models.Model):
    TRANSACTION_TYPES = [
        ('PURCHASE', 'Stock In'),
        ('SALE', 'Stock Out'),
        ('ADJUSTMENT', 'Adjustment'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_ledger')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    
    # We store the converted piece count here
    quantity = models.IntegerField(help_text="Quantity in pieces (Positive for In, Negative for Out)")
    
    # This will hold your Order Number or 'BULK_IMPORT_DATE'
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Stock Ledger"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.product.item_code} | {self.transaction_type} | {self.quantity}"















# --- C. ORDER & TRANSACTION MODELS ---

class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Payment'),
        ('PAID', 'Processing'),
        ('SHIPPED', 'In Transit'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]

    order_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='orders')
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    
    synced_to_erp = models.BooleanField(default=False)
    erp_reference = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"Order {self.order_number}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"















# --- 4. PAYMENT (M-PESA) MODELS ---

class MpesaTransaction(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='mpesa_payment')
    checkout_request_id = models.CharField(max_length=100, unique=True) 
    merchant_request_id = models.CharField(max_length=100)
    
    receipt_number = models.CharField(max_length=50, null=True, blank=True) 
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    phone_number = models.CharField(max_length=15)
    transaction_date = models.DateTimeField(null=True, blank=True)
    
    is_success = models.BooleanField(default=False)
    response_description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"M-Pesa {self.receipt_number or self.checkout_request_id}"