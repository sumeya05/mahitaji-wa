from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, CategoryViewSet, OrderViewSet
from . import views

router = DefaultRouter()
router.register(r'products', ProductViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'orders', OrderViewSet, basename='order')


urlpatterns = [
    # 1. The Website Home Page
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('cart/', views.cart, name='cart'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('about/', views.about, name='about'),
    path('statement/', views.statement, name='statement'),
    path('retailers/', views.retailers, name='retailers'),
    path('wholesalers/', views.wholesalers, name='wholesalers'),
    path('categories/', views.categories, name='categories'),
    path('brands/', views.brands, name='brands'),
    path('contact/', views.contact, name='contact'),
    path('location/', views.location, name='location'),
    path('pickups/', views.pickups, name='pickups'),
    path('payments/', views.payments, name='payments'),
    path('returns/', views.returns, name='returns'),
    path('faqs/', views.faqs, name='faqs'),
    path('terms/', views.terms, name='terms'),

    # 2. The API endpoints (accessed via /api/ products will be at /api/data/products)
    # Alternatively, keep them flat if you prefer
    path('data/', include(router.urls)), 
]