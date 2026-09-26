"""
Read-only JSON API (Django REST framework viewsets mounted at /data/).
"""
import logging

from django.db.models import Q, Sum
from rest_framework import permissions, viewsets

from ..models import (
    Brand, Category, Order, Product,
)
from ..serializers import BrandSerializer, CategorySerializer, OrderSerializer, ProductSerializer

logger = logging.getLogger(__name__)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = 'slug'


class BrandViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    lookup_field = 'slug'


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    # ``stock_total`` feeds Product.current_stock so the list endpoint does not
    # run one ledger aggregate per product.
    queryset = Product.objects.active().with_relations().annotate(stock_total=Sum('stock_ledger__quantity'))
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get('category'):
            queryset = queryset.filter(category__slug=params['category'])
        if params.get('brand'):
            queryset = queryset.filter(brand__slug=params['brand'])
        if params.get('q'):
            q = params['q']
            queryset = queryset.filter(Q(name__icontains=q) | Q(item_code__icontains=q) | Q(brand__name__icontains=q))
        return queryset.order_by('name')


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer
    lookup_field = 'order_number'

    def get_queryset(self):
        return Order.objects.filter(customer__user=self.request.user).prefetch_related('items__product')
