from rest_framework import serializers

from .models import Brand, Category, Order, OrderItem, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'image', 'description']


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug', 'logo']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    unit = serializers.CharField(source='pack_size', read_only=True)
    discount_percentage = serializers.CharField(read_only=True)
    current_stock = serializers.IntegerField(read_only=True)
    image_url = serializers.CharField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'item_code', 'name', 'slug', 'description',
            'category', 'category_name', 'brand', 'brand_name', 'unit',
            'retail_price', 'wholesale_price', 'old_price', 'discount_percentage',
            'current_stock', 'image', 'image_url', 'is_trending', 'is_best_seller',
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'product_name', 'quantity', 'price_at_purchase', 'subtotal']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.display_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'full_name', 'phone', 'address', 'city',
            'payment_method', 'total_amount', 'status', 'status_display', 'created_at', 'items',
        ]
        read_only_fields = ['order_number', 'total_amount', 'status']
