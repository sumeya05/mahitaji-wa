from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, CategoryViewSet, OrderViewSet
from . import views
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

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
    path('products/', views.products, name='products'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('categories/', views.categories, name='categories'),
    path('brands/', views.brands, name='brands'),
    path('offers/', views.offers, name='offers'),
    path('search/', views.search, name='search'),
    path('shopping-cart/', views.shopping_cart, name='shopping-cart'),
    path('cart-add/', views.cart_add, name='cart_add'),
    path('cart-delete/', views.cart_delete, name='cart_delete'),
    path('cart-update/', views.cart_update, name='cart_update'),
    path('checkout/', views.checkout, name='checkout'),
    path('place-order/', views.place_order, name='place-order'),
    path('order-success/<str:order_number>/', views.order_success, name='order-success'),

    # user routes
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('transactions/', views.transactions, name='transactions'),
    path('addresses/', views.addresses, name='addresses'),
    path('payment_methods/', views.payment_methods, name='payment_methods'),
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
    path('mpesa/pay/', views.initiate_stk_push, name='pay'),
    path('mpesa/callback/', views.mpesa_callback, name='callback'),

    # AI
    path('ai-assistant-chat/', views.ai_assistant_chat, name='ai_assistant_chat'),

    # non-sorted
    path('update-account/', views.update_account, name='update_account'),
    # URL for the Order Details Modal popup
    path('get-order-details/<int:order_id>/', views.get_order_details, name='get_order_details'),

]


# Add this at the very end
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)