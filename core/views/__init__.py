"""
Views for the Mahitaji storefront, grouped by area. ``core/urls.py`` does
``from . import views`` and refers to ``views.<name>``, so every view is
re-exported here; the module map is:

    storefront.py  home, product listings, search, categories, brands, product page
    cart.py        session cart page, drawer and AJAX endpoints
    checkout.py    checkout, order placement, order pages, cancellation
    payments.py    M-Pesa STK push, status polling, callback
    auth.py        login, register, logout, password reset
    account.py     dashboard, orders, addresses, settings, wishlist
    pages.py       help desk / company pages, contact, newsletter
    assistant.py   AI shopping assistant endpoint
    errors.py      404 / 500 handlers
    api.py         read-only REST viewsets (/data/)
    _common.py     helpers shared by the modules above

Conventions
-----------
* AJAX endpoints answer JSON shaped as ``{"ok": true, ...}`` or
  ``{"ok": false, "error": "summary", "errors": {"field": ["msg"]}}``.
* Any view that changes state is POST-only.
* Prices shown/charged depend on the customer's tier (retail/wholesale), see cart.py.
"""
from ._common import form_errors, get_profile, is_ajax, json_error, json_ok, request_data, safe_next_url  # noqa: F401
from .account import (  # noqa: F401
    address_delete, addresses, dashboard, payment_methods, transactions, update_account, wishlist, wishlist_toggle,
)
from .api import BrandViewSet, CategoryViewSet, OrderViewSet, ProductViewSet  # noqa: F401
from .assistant import ai_assistant_chat  # noqa: F401
from .auth import (  # noqa: F401
    custom_password_reset, custom_password_reset_confirm, login_view, logout_view, password_reset_complete,
    password_reset_done, register_view,
)
from .cart import cart_add, cart_delete, cart_update, mini_cart, shopping_cart  # noqa: F401
from .checkout import (  # noqa: F401
    checkout, get_order_details, order_cancel, order_detail, order_success, place_order,
)
from .errors import error_404, error_500  # noqa: F401
from .pages import (  # noqa: F401
    about, contact, faqs, location, newsletter_subscribe, payment_info, pickups, returns, statement, terms,
)
from .payments import check_payment_status, initiate_stk_push, mpesa_callback  # noqa: F401
from .storefront import (  # noqa: F401
    PAGE_SIZE, SORT_OPTIONS, brands, catalog, categories, home, offers, product_detail, products, retailers,
    search, search_suggest, wholesalers,
)

__all__ = [name for name in dir() if not name.startswith('_') and name not in ('form_errors', 'get_profile', 'is_ajax', 'json_error', 'json_ok', 'request_data', 'safe_next_url')] + [
    'form_errors', 'get_profile', 'is_ajax', 'json_error', 'json_ok', 'request_data', 'safe_next_url',
]
