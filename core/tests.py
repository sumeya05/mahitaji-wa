"""
Test-suite for the Mahitaji storefront. Runs against in-memory SQLite (see settings).

    python manage.py test core
"""
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .cart import Cart
from .models import (
    Address, Brand, Category, ContactMessage, CustomerProfile, MpesaTransaction,
    NewsletterSubscriber, Order, OrderItem, Product, StockLedger, UnitOfMeasure, WishlistItem,
)
from .services import MpesaError, process_stk_callback


def make_product(name="Golden Fry Cooking Oil 3L", item_code="BD001", retail="1050", wholesale="1020", old="1100", **extra):
    category, _ = Category.objects.get_or_create(name=extra.pop('category_name', 'Cooking Oils'))
    brand, _ = Brand.objects.get_or_create(name=extra.pop('brand_name', 'Bidco Africa'))
    uom, _ = UnitOfMeasure.objects.get_or_create(name='Piece', defaults={'short_name': 'pc', 'is_base_unit': True})
    return Product.objects.create(
        name=name, item_code=item_code, category=category, brand=brand, unit_of_measure=uom,
        retail_price=Decimal(retail) if retail else None, wholesale_price=Decimal(wholesale) if wholesale else None,
        old_price=Decimal(old) if old else None, **extra,
    )


def make_user(username="shop", email="shop@example.com", wholesaler=False, password="Str0ngPass!42"):
    user = User.objects.create_user(username=username, email=email, password=password, first_name="Jane", last_name="Doe")
    CustomerProfile.objects.create(user=user, phone_number="254712345678", is_wholesaler=wholesaler, business_name="Jane's Shop")
    return user


class ProductModelTests(TestCase):
    def test_discount_and_pricing(self):
        p = make_product()
        self.assertTrue(p.has_discount)
        self.assertEqual(p.discount_percentage, "4%")
        self.assertEqual(p.amount_saved, Decimal('50'))
        self.assertEqual(p.price_for('retail'), Decimal('1050'))
        self.assertEqual(p.price_for('wholesale'), Decimal('1020'))

    def test_no_discount_when_prices_missing(self):
        p = make_product(name="No old", item_code="X1", old=None)
        self.assertFalse(p.has_discount)
        self.assertIsNone(p.discount_percentage)
        p2 = make_product(name="No retail", item_code="X2", retail=None, wholesale="900", old="950")
        self.assertFalse(p2.has_discount)
        self.assertEqual(p2.price_for('retail'), Decimal('900'))  # falls back to wholesale

    def test_slug_uniqueness_and_placeholder(self):
        a = make_product(name="Same Name", item_code="S1")
        b = make_product(name="Same Name", item_code="S2")
        self.assertNotEqual(a.slug, b.slug)
        self.assertEqual(a.initials, "SN")
        self.assertTrue(0 <= a.placeholder_hue < 360)

    def test_initial_ledger_entry_created(self):
        p = make_product()
        self.assertEqual(p.stock_ledger.count(), 1)
        self.assertEqual(p.current_stock, 0)
        self.assertTrue(p.in_stock)  # no stock imported yet -> available to order


class CartTests(TestCase):
    def setUp(self):
        self.product = make_product()

    def test_guest_cart_uses_retail_prices(self):
        self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 2})
        res = self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 1},
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = res.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['cart']['qty'], 3)
        self.assertEqual(data['cart']['total'], 3150.0)
        self.assertIn('drawer_html', data)

    def test_wholesaler_is_charged_wholesale_price(self):
        user = make_user(wholesaler=True)
        self.client.force_login(user)
        self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 2})
        res = self.client.post(reverse('cart_update'), {'product_id': self.product.id, 'product_qty': 5},
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.json()['cart']['total'], 5 * 1020.0)

    def test_update_to_zero_removes_line_and_delete(self):
        self.client.post(reverse('cart_add'), {'product_id': self.product.id})
        self.client.post(reverse('cart_update'), {'product_id': self.product.id, 'product_qty': 0})
        session = self.client.session
        self.assertEqual(session['cart'], {})
        self.client.post(reverse('cart_add'), {'product_id': self.product.id})
        res = self.client.post(reverse('cart_delete'), {'product_id': self.product.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.json()['cart']['qty'], 0)

    def test_legacy_session_format_is_migrated(self):
        session = self.client.session
        session['cart'] = {str(self.product.id): {'price': '1050.00', 'qty': 4}}
        session.save()
        res = self.client.get(reverse('shopping-cart'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.session['cart'][str(self.product.id)], 4)

    def test_cart_get_is_rejected(self):
        self.assertEqual(self.client.get(reverse('cart_add')).status_code, 405)

    def test_inactive_products_are_dropped(self):
        self.client.post(reverse('cart_add'), {'product_id': self.product.id})
        self.product.is_active = False
        self.product.save()
        res = self.client.get(reverse('shopping-cart'))
        self.assertContains(res, "Your cart is empty")


class CatalogViewTests(TestCase):
    def setUp(self):
        self.oil = make_product()
        self.rice = make_product(name="Sunrice Basmati 2kg", item_code="KR1", retail="5400", wholesale="5200", old=None,
                                 category_name="Cereals", brand_name="Krish Commodities")
        make_product(name="Hidden", item_code="H1", is_active=False)

    def test_pages_render(self):
        for name in ['home', 'products', 'retailers', 'wholesalers', 'offers', 'categories', 'brands']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(self.oil.get_absolute_url()).status_code, 200)

    def test_inactive_product_is_404(self):
        hidden = Product.objects.get(item_code="H1")
        self.assertEqual(self.client.get(hidden.get_absolute_url()).status_code, 404)

    def test_filters_search_and_sort(self):
        res = self.client.get(reverse('products'), {'category': 'cereals'})
        self.assertContains(res, "Sunrice")
        self.assertNotContains(res, "Golden Fry")
        res = self.client.get(reverse('search'), {'q': 'bidco'})
        self.assertContains(res, "Golden Fry")
        res = self.client.get(reverse('products'), {'sort': 'price_desc'})
        body = res.content.decode()
        self.assertLess(body.index("Sunrice"), body.index("Golden Fry"))
        res = self.client.get(reverse('offers'))
        self.assertContains(res, "Golden Fry")
        self.assertNotContains(res, "Sunrice")

    def test_ajax_returns_fragment(self):
        res = self.client.get(reverse('products'), {'brand': 'bidco-africa'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = res.json()
        self.assertEqual(data['count'], 1)
        self.assertIn('Golden Fry', data['html'])

    def test_search_suggest(self):
        res = self.client.get(reverse('search_suggest'), {'q': 'gold'})
        self.assertEqual(res.json()['products'][0]['name'], "Golden Fry Cooking Oil 3L")

    def test_wholesalers_page_shows_wholesale_price(self):
        res = self.client.get(reverse('wholesalers'))
        self.assertContains(res, "KSh 1,020")
        self.assertContains(res, "wholesale prices")


class AuthTests(TestCase):
    def test_register_creates_profile_and_address(self):
        res = self.client.post(reverse('register'), {
            'first_name': 'Amina', 'last_name': 'Otieno', 'business_name': 'Amina Stores',
            'phone_number': '0712 345 678', 'email': 'AMINA@example.com', 'billing_address': 'Tom Mboya St',
            'city': 'Nairobi', 'password': 'Str0ngPass!42', 'confirm_password': 'Str0ngPass!42',
        })
        self.assertRedirects(res, reverse('dashboard'))
        user = User.objects.get(email='amina@example.com')
        self.assertEqual(user.username, 'amina-stores')
        self.assertEqual(user.customerprofile.phone_number, '254712345678')
        self.assertEqual(user.customerprofile.addresses.count(), 1)

    def test_register_rejects_duplicate_email_and_bad_phone(self):
        make_user()
        res = self.client.post(reverse('register'), {
            'first_name': 'A', 'last_name': 'B', 'phone_number': '12', 'email': 'shop@example.com',
            'password': 'Str0ngPass!42', 'confirm_password': 'Str0ngPass!42',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 400)
        errors = res.json()['errors']
        self.assertIn('email', errors)
        self.assertIn('phone_number', errors)

    def test_login_with_email_redirects_to_next(self):
        make_user()
        res = self.client.post(reverse('login'), {'username': 'shop@example.com', 'password': 'Str0ngPass!42', 'next': '/checkout/'})
        self.assertRedirects(res, '/checkout/', fetch_redirect_response=False)

    def test_login_failure_ajax(self):
        res = self.client.post(reverse('login'), {'username': 'nobody', 'password': 'x'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()['ok'])

    def test_password_reset_does_not_reveal_accounts(self):
        res = self.client.post(reverse('password_reset'), {'email': 'ghost@example.com'})
        self.assertRedirects(res, reverse('password_reset_done'))

    def test_account_pages_require_login(self):
        for name in ['dashboard', 'transactions', 'addresses', 'payment_methods', 'update_account', 'wishlist', 'checkout']:
            res = self.client.get(reverse(name))
            self.assertEqual(res.status_code, 302, name)
            self.assertIn(reverse('login'), res.url)


class CheckoutTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.user = make_user()
        self.client.force_login(self.user)
        self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 3})
        self.payload = {
            'first_name': 'Jane', 'last_name': 'Doe', 'email': 'shop@example.com', 'phone': '0712345678',
            'address': 'Baba Dogo Rd', 'city': 'Nairobi', 'payment_method': 'cod', 'save_address': True,
        }

    def _place(self, payload):
        return self.client.post(reverse('place-order'), data=json.dumps(payload), content_type='application/json')

    def test_empty_cart_redirects_from_checkout(self):
        self.client.post(reverse('cart_delete'), {'product_id': self.product.id})
        self.assertRedirects(self.client.get(reverse('checkout')), reverse('products'))

    def test_cod_order_is_created_and_cart_cleared(self):
        res = self._place(self.payload)
        data = res.json()
        self.assertTrue(data['ok'], data)
        order = Order.objects.get(order_number=data['order_number'])
        self.assertEqual(order.total_amount, Decimal('3150'))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().price_at_purchase, Decimal('1050'))
        self.assertEqual(order.payment_method, 'cod')
        self.assertEqual(self.client.session['cart'], {})
        self.assertTrue(Address.objects.filter(customer=self.user.customerprofile, is_primary=True).exists())
        # Success + detail pages render for the owner
        self.assertEqual(self.client.get(data['redirect_url']).status_code, 200)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 200)

    def test_validation_errors_are_returned(self):
        res = self._place({**self.payload, 'phone': 'abc', 'address': ''})
        self.assertEqual(res.status_code, 400)
        self.assertIn('phone', res.json()['errors'])
        self.assertIn('address', res.json()['errors'])
        self.assertEqual(Order.objects.count(), 0)

    @override_settings(MPESA_CALLBACK_URL='https://example.com/mpesa/callback/', MPESA_CONSUMER_KEY='k')
    def test_mpesa_order_sends_stk_push(self):
        fake = mock.Mock(checkout_request_id='ws_CO_1', merchant_request_id='m1', response_description='Success')
        with mock.patch('core.services._client') as client:
            client.return_value.stk_push.return_value = fake
            res = self._place({**self.payload, 'payment_method': 'mpesa', 'mpesa_phone': '0712345678'})
        data = res.json()
        self.assertTrue(data['payment']['sent'], data)
        txn = MpesaTransaction.objects.get(order__order_number=data['order_number'])
        self.assertEqual(txn.phone_number, '254712345678')
        client.return_value.stk_push.assert_called_once()
        self.assertEqual(client.return_value.stk_push.call_args[0][1], 3150)

    @override_settings(MPESA_CALLBACK_URL='')
    def test_mpesa_not_configured_still_creates_order(self):
        res = self._place({**self.payload, 'payment_method': 'mpesa', 'mpesa_phone': '0712345678'})
        data = res.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['payment']['sent'])
        self.assertEqual(Order.objects.get(order_number=data['order_number']).status, 'PENDING')

    def test_other_users_cannot_see_order(self):
        data = self._place(self.payload).json()
        other = make_user(username='other', email='other@example.com')
        self.client.force_login(other)
        self.assertEqual(self.client.get(data['redirect_url']).status_code, 404)

    def test_cancel_pending_order(self):
        data = self._place(self.payload).json()
        order = Order.objects.get(order_number=data['order_number'])
        self.client.post(reverse('order_cancel', args=[order.order_number]))
        order.refresh_from_db()
        self.assertEqual(order.status, 'CANCELLED')


class PaymentCallbackTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.user = make_user()
        self.order = Order.objects.create(order_number='MAH-TEST01', customer=self.user.customerprofile,
                                          total_amount=Decimal('2100'), payment_method='mpesa', email='shop@example.com')
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price_at_purchase=Decimal('1050'))
        self.txn = MpesaTransaction.objects.create(order=self.order, checkout_request_id='ws_CO_1', merchant_request_id='m',
                                                   amount=2100, phone_number='254712345678')

    def _callback(self, code, metadata=None):
        body = {'Body': {'stkCallback': {'MerchantRequestID': 'm', 'CheckoutRequestID': 'ws_CO_1', 'ResultCode': code, 'ResultDesc': 'x'}}}
        if metadata:
            body['Body']['stkCallback']['CallbackMetadata'] = {'Item': [{'Name': k, 'Value': v} for k, v in metadata.items()]}
        return self.client.post(reverse('callback'), data=json.dumps(body), content_type='application/json')

    def test_successful_callback_marks_paid_and_deducts_stock(self):
        res = self._callback(0, {'Amount': 2100, 'MpesaReceiptNumber': 'QAB12', 'TransactionDate': 20240521143012, 'PhoneNumber': 254712345678})
        self.assertEqual(res.json()['ResultCode'], 0)
        self.order.refresh_from_db(); self.txn.refresh_from_db()
        self.assertEqual(self.order.status, 'PAID')
        self.assertEqual(self.txn.receipt_number, 'QAB12')
        self.assertTrue(self.txn.is_success)
        self.assertEqual(self.product.current_stock, -2)
        self.assertEqual(StockLedger.objects.filter(reference_number='ORDER-MAH-TEST01').count(), 1)
        # Saving again must not double-deduct
        self.order.save()
        self.assertEqual(self.product.current_stock, -2)
        # Cancelling a paid order restocks once
        self.order.status = 'CANCELLED'; self.order.save()
        self.assertEqual(self.product.current_stock, 0)
        self.order.save()
        self.assertEqual(self.product.current_stock, 0)

    def test_failed_callback(self):
        self._callback(1032)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'FAILED')
        self.assertEqual(self.product.current_stock, 0)

    def test_unknown_or_malformed_callbacks(self):
        body = {'Body': {'stkCallback': {'CheckoutRequestID': 'nope', 'ResultCode': 0}}}
        res = self.client.post(reverse('callback'), data=json.dumps(body), content_type='application/json')
        self.assertEqual(res.json()['ResultCode'], 0)
        res = self.client.post(reverse('callback'), data='{"bad": 1}', content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_status_endpoint(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse('check_payment_status', args=[self.order.order_number]))
        self.assertEqual(res.json()['status'], 'pending')
        process_stk_callback({'Body': {'stkCallback': {'CheckoutRequestID': 'ws_CO_1', 'ResultCode': 0, 'CallbackMetadata': {'Item': []}}}})
        res = self.client.get(reverse('check_payment_status', args=[self.order.order_number]))
        self.assertEqual(res.json()['status'], 'paid')

    def test_stk_push_rejects_bad_phone(self):
        from .services import initiate_stk_push
        with self.assertRaises(MpesaError):
            initiate_stk_push(self.order, '123')


class AccountAndEngagementTests(TestCase):
    def setUp(self):
        self.product = make_product()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_wishlist_toggle(self):
        res = self.client.post(reverse('wishlist_toggle'), {'product_id': self.product.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(res.json()['added'])
        self.assertEqual(WishlistItem.objects.count(), 1)
        res = self.client.post(reverse('wishlist_toggle'), {'product_id': self.product.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(res.json()['added'])
        self.assertEqual(self.client.get(reverse('wishlist')).status_code, 200)

    def test_wishlist_requires_login(self):
        self.client.logout()
        res = self.client.post(reverse('wishlist_toggle'), {'product_id': self.product.id}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 401)

    def test_update_account_and_password(self):
        res = self.client.post(reverse('update_account'), {
            'form_type': 'account', 'first_name': 'Jane', 'last_name': 'Doe', 'email': 'new@example.com',
            'business_name': 'New Name', 'phone_number': '0722000000', 'tax_id': 'a012345678z',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(res.json()['ok'], res.json())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(self.user.customerprofile.tax_id, 'A012345678Z')
        res = self.client.post(reverse('update_account'), {
            'form_type': 'password', 'current_password': 'wrong', 'new_password': 'An0therPass!', 'confirm_password': 'An0therPass!',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 400)
        self.assertIn('current_password', res.json()['errors'])

    def test_addresses_crud(self):
        self.client.post(reverse('addresses'), {'label': 'Shop', 'physical_address': 'Moi Ave', 'city': 'Nairobi'})
        self.client.post(reverse('addresses'), {'label': 'Home', 'physical_address': 'Kiambu Rd', 'city': 'Kiambu', 'is_primary': 'on'})
        addresses = Address.objects.filter(customer=self.user.customerprofile)
        self.assertEqual(addresses.count(), 2)
        self.assertEqual(addresses.get(is_primary=True).label, 'Home')
        home = addresses.get(label='Home')
        self.client.post(reverse('address_delete', args=[home.id]))
        self.assertTrue(addresses.get().is_primary)

    def test_dashboard_pages_render(self):
        for name in ['dashboard', 'transactions', 'addresses', 'payment_methods', 'update_account']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class PublicFormsAndApiTests(TestCase):
    def test_contact_and_newsletter(self):
        res = self.client.post(reverse('contact'), {
            'full_name': 'Ali', 'email': 'ali@example.com', 'inquiry_type': 'order', 'message': 'Where is my order MAH-1?',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(res.json()['ok'])
        self.assertEqual(ContactMessage.objects.count(), 1)
        res = self.client.post(reverse('newsletter_subscribe'), {'email': 'ALI@example.com'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(res.json()['ok'])
        self.assertTrue(NewsletterSubscriber.objects.filter(email='ali@example.com').exists())

    def test_static_pages_render(self):
        for name in ['about', 'statement', 'contact', 'location', 'faqs', 'terms', 'returns', 'payment_info', 'pickups']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_api_is_read_only_and_orders_are_private(self):
        make_product()
        res = self.client.get('/data/products/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['count'], 1)
        self.assertIn(self.client.post('/data/products/', {'name': 'x'}).status_code, (403, 405))
        self.assertEqual(self.client.get('/data/orders/').status_code, 403)

    @override_settings(GEMINI_API_KEY='')
    def test_assistant_falls_back_to_catalogue(self):
        make_product()
        res = self.client.post(reverse('ai_assistant_chat'), {'message': 'price of cooking oil'})
        data = res.json()
        self.assertIn('Golden Fry', data['reply'])
        self.assertEqual(len(data['products']), 1)

    def test_404_page(self):
        res = self.client.get('/no-such-page/')
        self.assertEqual(res.status_code, 404)


class RegressionTests(TestCase):
    """Bugs found in the 2026-09-26 review; each test failed before its fix."""

    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        StockLedger.objects.create(product=self.product, transaction_type='PURCHASE', quantity=5, reference_number='OPENING')

    def _order(self, payment_method=Order.PAYMENT_COD, status=Order.STATUS_PENDING, qty=2):
        order = Order.objects.create(
            customer=self.user.customerprofile, payment_method=payment_method, status=status,
            total_amount=Decimal('2100'), full_name="Jane Doe", phone="254712345678",
        )
        OrderItem.objects.create(order=order, product=self.product, quantity=qty, price_at_purchase=Decimal('1050'))
        return order

    def test_order_number_is_generated_by_the_model(self):
        a, b = self._order(), self._order()
        self.assertTrue(a.order_number.startswith('MAH-'))
        self.assertNotEqual(a.order_number, b.order_number)

    def test_admin_order_pages_render(self):
        admin_user = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ngPass!42')
        self.client.force_login(admin_user)
        order = self._order()
        self.assertEqual(self.client.get(reverse('admin:core_order_add')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:core_order_change', args=[order.pk])).status_code, 200)

    def test_unsaved_order_item_subtotal_is_zero(self):
        self.assertEqual(OrderItem(product=self.product, quantity=1).subtotal, Decimal('0.00'))

    def test_cod_order_deducts_stock_when_shipped_and_restocks_on_cancel(self):
        order = self._order()
        self.assertEqual(self.product.current_stock, 5)
        order.status = Order.STATUS_SHIPPED
        order.save()
        self.assertEqual(self.product.current_stock, 3)
        order.status = Order.STATUS_DELIVERED
        order.save()
        self.assertEqual(self.product.current_stock, 3)  # not deducted twice
        order.status = Order.STATUS_CANCELLED
        order.save()
        self.assertEqual(self.product.current_stock, 5)

    def test_cancelled_mpesa_order_is_not_awaiting_payment(self):
        self.client.force_login(self.user)
        order = self._order(payment_method=Order.PAYMENT_MPESA, status=Order.STATUS_CANCELLED)
        response = self.client.get(reverse('order_detail', args=[order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['awaiting_payment'])
        response = self.client.post(reverse('pay'), {'order_number': order.order_number, 'phone': '254712345678'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertIn('cancelled', response.json()['error'].lower())

    def test_newsletter_resubscribe_is_accepted(self):
        NewsletterSubscriber.objects.create(email='again@example.com')
        response = self.client.post(reverse('newsletter_subscribe'), {'email': 'Again@Example.com'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NewsletterSubscriber.objects.filter(email='again@example.com').count(), 1)

    def test_wishlist_toggle_rejects_bad_product_id(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('wishlist_toggle'), {'product_id': 'abc'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)


class TierCarryThroughTests(TestCase):
    """Product links on the retailers/wholesalers pages keep that tier on the detail page."""

    def setUp(self):
        self.product = make_product(retail="1050", wholesale="1020")

    def test_wholesalers_page_links_carry_tier_for_retail_visitor(self):
        response = self.client.get(reverse('wholesalers'))
        self.assertContains(response, f"/product/{self.product.pk}/?tier=wholesale")
        response = self.client.get(reverse('products'))
        self.assertNotContains(response, "?tier=")

    def test_detail_page_shows_requested_tier_price(self):
        response = self.client.get(reverse('product_detail', args=[self.product.pk]) + "?tier=wholesale")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tier'], 'wholesale')
        self.assertContains(response, "Wholesale price")
        self.assertContains(response, "KSh 1,020")
        self.assertContains(response, "charged at retail")

    def test_detail_page_ignores_bogus_or_own_tier(self):
        response = self.client.get(reverse('product_detail', args=[self.product.pk]) + "?tier=bogus")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('tier_notice', response.context)
        self.assertContains(response, "KSh 1,050")
        self.client.force_login(make_user(wholesaler=True))
        response = self.client.get(reverse('product_detail', args=[self.product.pk]) + "?tier=wholesale")
        self.assertNotIn('tier_notice', response.context)
        self.assertContains(response, "KSh 1,020")

    def test_retailers_page_links_carry_tier_for_wholesale_account(self):
        self.client.force_login(make_user(wholesaler=True))
        response = self.client.get(reverse('retailers'))
        self.assertContains(response, f"/product/{self.product.pk}/?tier=retail")
        response = self.client.get(reverse('product_detail', args=[self.product.pk]) + "?tier=retail")
        self.assertContains(response, "KSh 1,050")
        self.assertContains(response, "charged at wholesale")


class EfficiencyAndDisplayTests(TestCase):
    """Full unit names, cached navigation lists and the annotated API stock."""

    def test_pack_size_uses_full_unit_name_normalised(self):
        uom = UnitOfMeasure.objects.create(name='DOZEN', short_name='dzn')
        p = make_product(name="Eggs", item_code="EG1")
        p.unit_of_measure = uom
        p.save()
        self.assertEqual(p.pack_size, 'Dozen')
        response = self.client.get(reverse('products'))
        self.assertContains(response, 'Dozen')
        self.assertNotContains(response, '>dzn<')

    def test_navigation_cache_is_invalidated_when_catalogue_changes(self):
        from django.core.cache import cache
        cache.clear()
        make_product(name="One", item_code="C1", category_name="Cereals")
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Cereals')
        make_product(name="Two", item_code="C2", category_name="Drinks")
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Drinks')
        Category.objects.filter(name='Drinks').delete()
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'Drinks')

    def test_api_product_list_reports_stock_without_per_product_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(6):
            p = make_product(name=f"P{i}", item_code=f"P{i}")
            StockLedger.objects.create(product=p, transaction_type='PURCHASE', quantity=3 + i, reference_number='X')
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get('/data/products/')
        self.assertEqual(response.status_code, 200)
        stocks = {r['name']: r['current_stock'] for r in response.json()['results']}
        self.assertEqual(stocks['P0'], 3)
        self.assertEqual(stocks['P5'], 8)
        self.assertEqual(response.json()['results'][0]['unit'], 'Piece')
        ledger_queries = [q['sql'] for q in ctx.captured_queries if 'core_stockledger' in q['sql'] and 'core_product' not in q['sql']]
        self.assertEqual(ledger_queries, [])


class TierAwareDiscountTests(TestCase):
    """Wholesale views never show the retail price as a struck-through 'was' price."""

    def setUp(self):
        self.both = make_product(name="Both Tiers", item_code="T1", retail="1050", wholesale="900", old="1200")
        self.retail_only = make_product(name="Retail Only", item_code="T2", retail="500", wholesale=None, old="600")

    def test_wholesale_card_shows_no_retail_strikethrough(self):
        response = self.client.get(reverse('wholesalers'))
        html = response.content.decode()
        self.assertIn("KSh 900", html)
        self.assertNotIn('<span class="was">KSh 1,050</span>', html)
        self.assertNotIn("-12%", html)  # the retail offer badge must not leak into the wholesale view

    def test_wholesale_offer_uses_old_wholesale_price(self):
        self.both.old_wholesale_price = Decimal('1000')
        self.both.save()
        response = self.client.get(reverse('wholesalers'))
        html = response.content.decode()
        self.assertIn('<span class="was">KSh 1,000</span>', html)
        self.assertIn("-10%", html)
        self.assertEqual(list(Product.objects.on_offer('wholesale')), [self.both])
        self.assertEqual(set(Product.objects.on_offer('retail')), {self.both, self.retail_only})

    def test_wholesalers_page_lists_only_products_with_wholesale_price(self):
        response = self.client.get(reverse('wholesalers'))
        self.assertContains(response, "Both Tiers")
        self.assertNotContains(response, "Retail Only")
        response = self.client.get(reverse('products'))
        self.assertContains(response, "Retail Only")

    def test_wholesaler_sees_retail_label_when_no_wholesale_price(self):
        self.client.force_login(make_user(wholesaler=True))
        response = self.client.get(reverse('product_detail', args=[self.retail_only.pk]))
        html = response.content.decode()
        self.assertRegex(html, r'pd-price">\s*<span class="tier">Retail price</span>')
        self.assertIn("KSh 500", html)
        response = self.client.get(reverse('product_detail', args=[self.both.pk]))
        self.assertRegex(response.content.decode(), r'pd-price">\s*<span class="tier">Wholesale price</span>')

    def test_offers_page_is_tier_specific(self):
        self.client.force_login(make_user(wholesaler=True))
        self.assertEqual(self.client.get(reverse('offers')).context['total_count'], 0)
        self.both.old_wholesale_price = Decimal('1000')
        self.both.save()
        self.assertEqual(self.client.get(reverse('offers')).context['total_count'], 1)


@override_settings(ASSISTANT_RATE_LIMIT=5, ASSISTANT_DAILY_LLM_LIMIT=100)
class AssistantTests(TestCase):
    """Deterministic answers, rate limiting, history hand-off to the model, and logging."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = make_user()
        self.oil = make_product(name="Golden Fry Cooking Oil 3L", item_code="OIL1", retail="1050", wholesale="900", old="1100")
        self.rice = make_product(name="Amana Long Grain Rice 24x1kg", item_code="RICE1", retail="3200", wholesale="3000",
                                 old=None, category_name="Rice")

    def ask(self, message, history=None):
        payload = {'message': message}
        if history is not None:
            payload['history'] = history
        return self.client.post(reverse('ai_assistant_chat'), json.dumps(payload), content_type='application/json',
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_price_question_is_answered_from_catalogue_without_a_model(self):
        with mock.patch('core.assistant._generate') as generate:
            response = self.ask("What is the price of cooking oil?")
        generate.assert_not_called()
        data = response.json()
        self.assertEqual(data['handled_by'], 'catalogue')
        self.assertIn("KSh 1,050", data['reply'])
        self.assertIn("was KSh 1,100", data['reply'])
        self.assertEqual(data['products'][0]['name'], "Golden Fry Cooking Oil 3L")

    def test_wholesaler_gets_wholesale_prices(self):
        self.client.force_login(make_user(username='ws', email='ws@x.com', wholesaler=True))
        data = self.ask("how much is rice?").json()
        self.assertEqual(data['handled_by'], 'catalogue')
        self.assertIn("KSh 3,000", data['reply'])
        self.assertIn("wholesale prices", data['reply'])

    def test_faq_delivery_and_payment(self):
        self.assertIn("next working day", self.ask("Do you deliver outside Nairobi?").json()['reply'])
        data = self.ask("How do I pay with M-Pesa?").json()
        self.assertEqual(data['handled_by'], 'faq')
        self.assertIn("STK prompt", data['reply'])

    def test_order_status_requires_sign_in_then_reports_latest_order(self):
        self.assertIn("Sign in", self.ask("Where is my order?").json()['reply'])
        self.client.force_login(self.user)
        self.assertIn("haven't placed any orders", self.ask("where is my order").json()['reply'])
        order = Order.objects.create(customer=self.user.customerprofile, payment_method=Order.PAYMENT_MPESA,
                                     status=Order.STATUS_PENDING, total_amount=Decimal('2100'), full_name="Jane Doe")
        OrderItem.objects.create(order=order, product=self.oil, quantity=2, price_at_purchase=Decimal('1050'))
        data = self.ask(f"track {order.order_number}").json()
        self.assertEqual(data['handled_by'], 'order')
        self.assertIn(order.order_number, data['reply'])
        self.assertIn("Pending", data['reply'])
        self.assertIn("awaiting M-Pesa payment", data['reply'])
        self.assertIn("couldn't find MAH-ZZZZZZZZ", self.ask("order MAH-ZZZZZZZZ status").json()['reply'])

    @override_settings(GEMINI_API_KEY='test-key')
    def test_free_form_question_goes_to_model_with_history_and_products(self):
        history = [{'role': 'user', 'text': 'hi'}, {'role': 'assistant', 'text': 'Hello!'}, {'role': 'bogus', 'text': 'x'}, 'junk']
        with mock.patch('core.assistant._generate', return_value="Try the Golden Fry oil.") as generate:
            data = self.ask("Which cooking oil is best for chips?", history).json()
        self.assertEqual(data['handled_by'], 'llm')
        self.assertEqual(data['reply'], "Try the Golden Fry oil.")
        system_prompt, sent_history, message = generate.call_args[0]
        self.assertEqual(sent_history, [{'role': 'user', 'text': 'hi'}, {'role': 'assistant', 'text': 'Hello!'}])
        self.assertEqual(message, "Which cooking oil is best for chips?")
        self.assertIn("never invent products or prices", system_prompt)
        self.assertIn("Golden Fry Cooking Oil 3L", system_prompt)

    @override_settings(GEMINI_API_KEY='test-key')
    def test_model_failure_degrades_gracefully(self):
        with mock.patch('core.assistant._generate', side_effect=RuntimeError("429 quota")):
            data = self.ask("Which of these is best for chips?").json()
        self.assertEqual(data['handled_by'], 'fallback')
        self.assertIn("try again", data['reply'])

    def test_rate_limit_and_message_length(self):
        for _ in range(5):
            self.assertEqual(self.ask("hello there").status_code, 200)
        response = self.ask("hello again")
        self.assertEqual(response.status_code, 429)
        self.assertIn("very quickly", response.json()['error'])
        from django.core.cache import cache
        cache.clear()
        self.assertEqual(self.ask("x" * 600).status_code, 400)

    def test_every_exchange_is_logged(self):
        from core.models import ChatMessage
        self.client.force_login(self.user)
        self.ask("price of rice")
        self.ask("do you deliver?")
        rows = list(ChatMessage.objects.order_by('created_at'))
        self.assertEqual([r.handled_by for r in rows], ['catalogue', 'faq'])
        self.assertEqual(rows[0].user, self.user)
        self.assertEqual(rows[0].product_ids, [self.rice.id])

    @override_settings(GEMINI_API_KEY='test-key')
    def test_advisory_price_question_goes_to_model_with_products(self):
        with mock.patch('core.assistant._generate', return_value="The Golden Fry oil suits chips.") as generate:
            data = self.ask("Which cooking oil would you recommend, and is it on offer?").json()
        self.assertEqual(data['handled_by'], 'llm')
        self.assertIn("Golden Fry Cooking Oil 3L", generate.call_args[0][0])
        self.assertEqual(data['products'][0]['name'], "Golden Fry Cooking Oil 3L")
