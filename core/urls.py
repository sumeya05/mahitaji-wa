from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, CategoryViewSet, OrderViewSet
from . import views
from django.contrib.auth import views as auth_views

router = DefaultRouter()
router.register(r'products', ProductViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'orders', OrderViewSet, basename='order')


urlpatterns = [

    # 1. Templates Routes

    # landing page
    path('', views.home, name='home'),

    # sales routes
    path('retailers/', views.retailers, name='retailers'),
    path('wholesalers/', views.wholesalers, name='wholesalers'),
    path('categories/', views.categories, name='categories'),
    path('brands/', views.brands, name='brands'),
    path('search/', views.search, name='search'),
    path('cart/', views.cart, name='cart'),
    path('checkout/', views.checkout, name='checkout'),

    # user routes
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup, name='signup'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('transactions/', views.transactions, name='transactions'),
    path('addresses/', views.addresses, name='addresses'),
    path('payment_methods/', views.payment_methods, name='payment_methods'),
    path('settings/', views.settings, name='settings'),
    path('logout/', views.logout_view, name='logout'),

    path('password-reset/', views.custom_password_reset, name='password_reset'),
    path('password-reset/done/', views.password_reset_done, name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.custom_password_reset_confirm, name='password_reset_confirm'),
    path('reset/done/', views.password_reset_complete, name='password_reset_complete'),
    
    # helpdesk    
    path('pickups/', views.pickups, name='pickups'),
    path('payment-info/', views.payment_info, name='payment_info'),
    path('return-policy/', views.returns, name='returns'),
    path('faqs/', views.faqs, name='faqs'),
    path('terms/', views.terms, name='terms'),
    path('contact/', views.contact, name='contact'),

    # informational routes
    path('about/', views.about, name='about'),
    path('statement/', views.statement, name='statement'),
    path('location/', views.location, name='location'),   
    

    # 2. API endpoints 
    
    # accessed via /api/ - i.e products will be at /api/data/products
    path('data/', include(router.urls)), 

    # mpesa
    path('pay/', views.initiate_stk_push, name='pay'),
    path('mpesa/callback/', views.mpesa_callback, name='callback'),

]