from django.shortcuts import render
from rest_framework import viewsets, permissions
from .models import Product, Category, Order, CustomerProfile
from .serializers import ProductSerializer, CategorySerializer, OrderSerializer

# API Endpoints for Products, Categories, and Orders

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        category_slug = self.request.query_params.get('category')
        
        # Filter by category if provided in URL (e.g. ?category=maize-flour)
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

class OrderViewSet(viewsets.ModelViewSet):
    # Only authenticated users can see their orders
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        # Users only see their own orders (critical for the Dashboard)
        return Order.objects.filter(customer__user=self.request.user)

    def perform_create(self, serializer):
        # Auto-assign the order to the logged-in customer
        customer = CustomerProfile.objects.get(user=self.request.user)
        serializer.save(customer=customer)


# Views for rendering templates (e.g., home page, product listing)

def home(request):
    return render(request, 'core/home.html')

def retailers(request):
    return render(request, 'core/retailers.html')

def wholesalers(request):
    return render(request, 'core/wholesalers.html') 

def categories(request):
    return render(request, 'core/categories.html')

def brands(request):
    return render(request, 'core/brands.html')

def search(request):
    return render(request, 'core/search.html')

def cart(request):
    return render(request, 'core/cart.html')

def dashboard(request):
    return render(request, 'core/dashboard.html')

def about(request):
    return render(request, 'core/about.html')

def statement(request):
    return render(request, 'core/statement.html')

def contact(request):
    return render(request, 'core/contact.html') 

def location(request):
    return render(request, 'core/location.html')

# footer views
def pickups(request):
    return render(request, 'core/pickups.html')

def payments(request):
    return render(request, 'core/payments.html')

def returns(request):
    return render(request, 'core/returns.html')

def faqs(request):
    return render(request, 'core/faqs.html')

def terms(request):
    return render(request, 'core/terms.html')   