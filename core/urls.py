from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .views import mobile
from .views import BrandViewSet, CategoryViewSet, OrderViewSet, ProductViewSet

router = DefaultRouter()
router.register(r'products', ProductViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'brands', BrandViewSet)
router.register(r'orders', OrderViewSet, basename='order')

mobile_urlpatterns = [
    path('config/', mobile.ConfigView.as_view(), name='config'),
    path('home/', mobile.HomeView.as_view(), name='home'),
    path('categories/', mobile.CategoryListView.as_view(), name='categories'),
    path('brands/', mobile.BrandListView.as_view(), name='brands'),
    path('products/', mobile.ProductListView.as_view(), name='products'),
    path('products/<int:pk>/', mobile.ProductDetailView.as_view(), name='product'),
    path('cart/quote/', mobile.CartQuoteView.as_view(), name='cart_quote'),
    path('auth/login/', mobile.LoginView.as_view(), name='login'),
    path('auth/register/', mobile.RegisterView.as_view(), name='register'),
    path('auth/logout/', mobile.LogoutView.as_view(), name='logout'),
    path('auth/password-reset/', mobile.PasswordResetView.as_view(), name='password_reset'),
    path('me/', mobile.MeView.as_view(), name='me'),
    path('me/password/', mobile.PasswordChangeView.as_view(), name='password_change'),
    path('addresses/', mobile.AddressListView.as_view(), name='addresses'),
    path('addresses/<int:pk>/', mobile.AddressDetailView.as_view(), name='address'),
    path('wishlist/', mobile.WishlistView.as_view(), name='wishlist'),
    path('wishlist/toggle/', mobile.WishlistToggleView.as_view(), name='wishlist_toggle'),
    path('orders/', mobile.OrderListView.as_view(), name='orders'),
    path('orders/<str:order_number>/', mobile.OrderDetailView.as_view(), name='order'),
    path('orders/<str:order_number>/payment-status/', mobile.PaymentStatusView.as_view(), name='payment_status'),
    path('orders/<str:order_number>/<str:action>/', mobile.OrderActionView.as_view(), name='order_action'),
    path('contact/', mobile.ContactView.as_view(), name='contact'),
]

urlpatterns = [
    # Storefront
    path('', views.home, name='home'),
    path('products/', views.products, name='products'),
    path('retailers/', views.retailers, name='retailers'),
    path('wholesalers/', views.wholesalers, name='wholesalers'),
    path('offers/', views.offers, name='offers'),
    path('search/', views.search, name='search'),
    path('categories/', views.categories, name='categories'),
    path('brands/', views.brands, name='brands'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('search/suggest/', views.search_suggest, name='search_suggest'),
    path('price-list.csv', views.price_list, name='price_list'),

    # Cart
    path('shopping-cart/', views.shopping_cart, name='shopping-cart'),
    path('mini-cart/', views.mini_cart, name='mini-cart'),
    path('cart-add/', views.cart_add, name='cart_add'),
    path('cart-delete/', views.cart_delete, name='cart_delete'),
    path('cart-update/', views.cart_update, name='cart_update'),
    path('coupon/', views.apply_coupon, name='apply_coupon'),

    # Checkout & orders
    path('checkout/', views.checkout, name='checkout'),
    path('place-order/', views.place_order, name='place-order'),
    path('order-success/<str:order_number>/', views.order_success, name='order-success'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('orders/<str:order_number>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/<str:order_number>/pay-on-delivery/', views.order_pay_on_delivery, name='order_pay_on_delivery'),
    path('orders/<str:order_number>/pdf/', views.order_pdf, name='order_pdf'),
    path('get-order-details/<int:order_id>/', views.get_order_details, name='get_order_details'),

    # Payments (M-Pesa)
    path('mpesa/pay/', views.initiate_stk_push, name='pay'),
    # Safaricom is given this URL with a secret token (core.services.callback_url). There is no
    # token-less route: a callback that cannot present the token is never taken at its word.
    path('mpesa/callback/<str:token>/', views.mpesa_callback, name='callback_token'),
    path('check-payment-status/<str:order_number>/', views.check_payment_status, name='check_payment_status'),

    # Auth
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', views.custom_password_reset, name='password_reset'),
    path('password-reset/done/', views.password_reset_done, name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.custom_password_reset_confirm, name='password_reset_confirm'),
    path('reset/done/', views.password_reset_complete, name='password_reset_complete'),

    # Account
    path('dashboard/', views.dashboard, name='dashboard'),
    path('transactions/', views.transactions, name='transactions'),
    path('addresses/', views.addresses, name='addresses'),
    path('addresses/<int:pk>/delete/', views.address_delete, name='address_delete'),
    path('payment_methods/', views.payment_methods, name='payment_methods'),
    path('update-account/', views.update_account, name='update_account'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/toggle/', views.wishlist_toggle, name='wishlist_toggle'),

    # Help desk & company
    path('pickups/', views.pickups, name='pickups'),
    path('payment-info/', views.payment_info, name='payment_info'),
    path('return-policy/', views.returns, name='returns'),
    path('faqs/', views.faqs, name='faqs'),
    path('terms/', views.terms, name='terms'),
    path('contact/', views.contact, name='contact'),
    path('about/', views.about, name='about'),
    path('statement/', views.statement, name='statement'),
    path('location/', views.location, name='location'),
    path('newsletter/subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),

    # AI assistant
    path('ai-assistant-chat/', views.ai_assistant_chat, name='ai_assistant_chat'),

    # JSON API (browsable at /data/)
    path('data/', include(router.urls)),

    # Mobile app API (token authentication, see core/views/mobile.py)
    path('api/v1/', include((mobile_urlpatterns, 'mobile'))),
]
