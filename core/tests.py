"""
Test-suite for the Mahitaji storefront. Runs against in-memory SQLite (see settings).

    python manage.py test core
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from django.core.cache import cache

from .cart import Cart
from .models import (
    Address, Brand, Category, ContactMessage, Coupon, CustomerProfile, MpesaTransaction,
    NewsletterSubscriber, Order, OrderItem, Product, StockLedger, UnitOfMeasure, WishlistItem,
)
from .services import MpesaError, callback_token, process_stk_callback, sync_order_stock


def add_stock(product, quantity, reference='OPENING'):
    """Receive stock for a product, which also starts tracking it."""
    return StockLedger.objects.create(product=product, transaction_type='PURCHASE', quantity=quantity, reference_number=reference)


def make_product(name="Golden Fry Cooking Oil 3L", item_code="BD001", retail="1050", wholesale="1020", old="1100", **extra):
    category, _ = Category.objects.get_or_create(name=extra.pop('category_name', 'Cooking Oils'))
    brand, _ = Brand.objects.get_or_create(name=extra.pop('brand_name', 'Bidco Africa'))
    uom, _ = UnitOfMeasure.objects.get_or_create(name='Piece', defaults={'short_name': 'pc', 'is_base_unit': True})
    return Product.objects.create(
        name=name, item_code=item_code, category=category, brand=brand, unit_of_measure=uom,
        retail_price=Decimal(retail) if retail else None, wholesale_price=Decimal(wholesale) if wholesale else None,
        old_retail_price=Decimal(old) if old else None, **extra,
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
        cache.clear()
        self.product = make_product()
        add_stock(self.product, 10)
        self.user = make_user()
        self.order = Order.objects.create(order_number='MAH-TEST01', customer=self.user.customerprofile,
                                          total_amount=Decimal('2100'), payment_method='mpesa', email='shop@example.com')
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price_at_purchase=Decimal('1050'))
        sync_order_stock(self.order)  # what checkout does once the lines exist
        self.txn = MpesaTransaction.objects.create(order=self.order, checkout_request_id='ws_CO_1', merchant_request_id='m',
                                                   amount=2100, phone_number='254712345678')

    PAID = {'Amount': 2100, 'MpesaReceiptNumber': 'QAB12', 'TransactionDate': 20240521143012, 'PhoneNumber': 254712345678}

    def _body(self, code, metadata=None, checkout_id='ws_CO_1'):
        body = {'Body': {'stkCallback': {'MerchantRequestID': 'm', 'CheckoutRequestID': checkout_id, 'ResultCode': code, 'ResultDesc': 'x'}}}
        if metadata:
            body['Body']['stkCallback']['CallbackMetadata'] = {'Item': [{'Name': k, 'Value': v} for k, v in metadata.items()]}
        return body

    def _callback(self, code, metadata=None, trusted=True, checkout_id='ws_CO_1'):
        """Post a callback the way Safaricom does: on the secret URL unless ``trusted`` is False."""
        url = reverse('callback_token', args=[callback_token()]) if trusted else reverse('callback')
        return self.client.post(url, data=json.dumps(self._body(code, metadata, checkout_id)), content_type='application/json')

    def test_successful_callback_marks_paid_and_keeps_stock_booked(self):
        self.assertEqual(self.product.current_stock, 8)  # held since the order was placed
        res = self._callback(0, self.PAID)
        self.assertEqual(res.json()['ResultCode'], 0)
        self.order.refresh_from_db(); self.txn.refresh_from_db()
        self.assertEqual(self.order.status, 'PAID')
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.txn.receipt_number, 'QAB12')
        self.assertTrue(self.txn.is_success)
        self.assertEqual(self.txn.state, 'paid')
        self.assertEqual(self.product.current_stock, 8)
        # Saving again must not double-deduct
        self.order.save()
        self.assertEqual(self.product.current_stock, 8)
        # Cancelling releases the stock once, and a paid cancelled order is flagged for refund
        self.order.status = 'CANCELLED'; self.order.save()
        self.assertEqual(self.product.current_stock, 10)
        self.order.save()
        self.assertEqual(self.product.current_stock, 10)
        self.assertTrue(self.order.needs_refund)

    def test_failed_callback(self):
        self._callback(1032)
        self.order.refresh_from_db(); self.txn.refresh_from_db()
        self.assertEqual(self.order.status, 'FAILED')
        self.assertEqual(self.txn.state, 'failed')
        self.assertEqual(self.product.current_stock, 8)  # still held: the customer can retry

    def test_callback_without_the_secret_is_confirmed_with_safaricom(self):
        # Anyone can post to the plain URL, so a payment it reports is checked with Safaricom first.
        with mock.patch('core.services.query_stk_status', return_value=(None, 'still processing')) as query:
            self._callback(0, self.PAID, trusted=False)
        query.assert_called_once()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PENDING')
        self.assertFalse(self.order.is_paid)
        with mock.patch('core.services.query_stk_status', side_effect=MpesaError('down')):
            self._callback(0, self.PAID, trusted=False)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)
        with mock.patch('core.services.query_stk_status', return_value=(True, 'ok')):
            self._callback(0, self.PAID, trusted=False)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)

    def test_wrong_token_is_not_trusted(self):
        url = reverse('callback_token', args=['not-the-token'])
        with mock.patch('core.services.query_stk_status', return_value=(False, 'cancelled by user')):
            self.client.post(url, data=json.dumps(self._body(0, self.PAID)), content_type='application/json')
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_underpaid_callback_is_not_accepted(self):
        self._callback(0, {**self.PAID, 'Amount': 1})
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_late_failure_does_not_undo_a_payment(self):
        self._callback(0, self.PAID)
        self._callback(1032)
        self.order.refresh_from_db(); self.txn.refresh_from_db()
        self.assertTrue(self.txn.is_success)
        self.assertEqual(self.order.status, 'PAID')

    def test_paying_an_older_prompt_still_counts(self):
        # The customer asked for a second prompt, then approved the first one.
        MpesaTransaction.objects.create(order=self.order, checkout_request_id='ws_CO_2', merchant_request_id='m2',
                                        amount=2100, phone_number='254712345678')
        self._callback(0, self.PAID, checkout_id='ws_CO_1')
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.order.latest_payment.checkout_request_id, 'ws_CO_1')
        # A failure of the abandoned second prompt changes nothing.
        self._callback(1032, checkout_id='ws_CO_2')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PAID')

    def test_payment_for_a_cancelled_order_is_recorded_for_refund(self):
        self.order.status = 'CANCELLED'; self.order.save()
        self._callback(0, self.PAID)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELLED')
        self.assertTrue(self.order.needs_refund)

    def test_unknown_or_malformed_callbacks(self):
        res = self._callback(0, checkout_id='nope')
        self.assertEqual(res.json()['ResultCode'], 0)
        res = self.client.post(reverse('callback'), data='{"bad": 1}', content_type='application/json')
        self.assertEqual(res.status_code, 400)
        res = self.client.post(reverse('callback'), data='[1, 2]', content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_status_endpoint(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse('check_payment_status', args=[self.order.order_number]))
        self.assertEqual(res.json()['status'], 'pending')
        process_stk_callback(self._body(0, {'Amount': 2100}), trusted=True)
        res = self.client.get(reverse('check_payment_status', args=[self.order.order_number]))
        self.assertEqual(res.json()['status'], 'paid')

    @override_settings(MPESA_CALLBACK_URL='https://example.com/mpesa/callback/', MPESA_CONSUMER_KEY='k')
    def test_status_endpoint_asks_safaricom_when_no_callback_arrived(self):
        self.client.force_login(self.user)
        with mock.patch('core.services.query_stk_status', return_value=(True, 'The service request is processed successfully.')) as query:
            res = self.client.get(reverse('check_payment_status', args=[self.order.order_number]))
        query.assert_called_once()
        self.assertEqual(res.json()['status'], 'paid')
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)

    def test_stk_push_rejects_bad_phone(self):
        from .services import initiate_stk_push
        with self.assertRaises(MpesaError):
            initiate_stk_push(self.order, '123')

    @override_settings(MPESA_CALLBACK_URL='https://example.com/mpesa/callback/', MPESA_CONSUMER_KEY='k')
    def test_prompt_uses_secret_callback_url_hides_request_id_and_is_throttled(self):
        self.client.force_login(self.user)
        fake = mock.Mock(checkout_request_id='ws_CO_9', merchant_request_id='m9', response_description='Success')
        with mock.patch('core.services._client') as client:
            client.return_value.stk_push.return_value = fake
            res = self.client.post(reverse('pay'), {'order_number': self.order.order_number, 'phone': '0712345678'},
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            again = self.client.post(reverse('pay'), {'order_number': self.order.order_number, 'phone': '0712345678'},
                                     HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(res.json()['ok'], res.json())
        self.assertNotIn('ws_CO_9', res.content.decode())
        self.assertEqual(client.return_value.stk_push.call_args[0][4], f'https://example.com/mpesa/callback/{callback_token()}/')
        self.assertEqual(again.status_code, 502)  # a second prompt seconds later is refused
        self.assertEqual(self.order.mpesa_payments.count(), 2)  # the first attempt is kept


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

    def test_order_holds_stock_until_cancelled(self):
        order = self._order()
        self.assertEqual(self.product.current_stock, 5)
        sync_order_stock(order)  # checkout books the stock as soon as the lines exist
        self.assertEqual(self.product.current_stock, 3)
        order.status = Order.STATUS_SHIPPED
        order.save()
        order.status = Order.STATUS_DELIVERED
        order.save()
        self.assertEqual(self.product.current_stock, 3)  # not deducted twice
        order.status = Order.STATUS_CANCELLED
        order.save()
        self.assertEqual(self.product.current_stock, 5)
        order.status = Order.STATUS_PENDING  # reinstated in the admin
        order.save()
        self.assertEqual(self.product.current_stock, 3)

    def test_untracked_products_are_not_booked(self):
        loose = make_product(name="No Stock Records", item_code="NS1")
        order = self._order()
        OrderItem.objects.create(order=order, product=loose, quantity=4, price_at_purchase=Decimal('1050'))
        sync_order_stock(order)
        self.assertEqual(loose.current_stock, 0)
        self.assertEqual(loose.stock_state, '')
        self.assertEqual(self.product.current_stock, 3)

    def test_cash_on_delivery_is_paid_when_delivered_not_when_shipped(self):
        order = self._order()
        order.status = Order.STATUS_SHIPPED
        order.save()
        self.assertFalse(order.is_paid)
        order.status = Order.STATUS_DELIVERED
        order.save()
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertFalse(order.can_cancel)

    def test_failed_mpesa_order_can_switch_to_pay_on_delivery(self):
        self.client.force_login(self.user)
        order = self._order(payment_method=Order.PAYMENT_MPESA, status=Order.STATUS_FAILED)
        page = self.client.get(reverse('order_detail', args=[order.order_number]))
        self.assertContains(page, 'Pay on delivery instead')
        self.assertContains(page, 'class="pay-options mt-3"')          # shown straight away after a failure
        response = self.client.post(reverse('order_pay_on_delivery', args=[order.order_number]))
        self.assertRedirects(response, reverse('order_detail', args=[order.order_number]), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, Order.PAYMENT_COD)
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertFalse(order.can_pay)
        self.assertTrue(order.can_cancel)
        page = self.client.get(reverse('order_detail', args=[order.order_number]))
        self.assertContains(page, 'Pay on delivery')
        self.assertNotContains(page, 'id="payOptions"')
        self.assertContains(page, 'will be paid on delivery')

    def test_pay_on_delivery_switch_is_refused_for_paid_or_cod_orders(self):
        self.client.force_login(self.user)
        for order in (self._order(payment_method=Order.PAYMENT_MPESA, status=Order.STATUS_PAID),
                      self._order(payment_method=Order.PAYMENT_COD)):
            before = (order.payment_method, order.status)
            self.client.post(reverse('order_pay_on_delivery', args=[order.order_number]))
            order.refresh_from_db()
            self.assertEqual((order.payment_method, order.status), before)
        self.assertEqual(self.client.get(reverse('order_pay_on_delivery', args=[order.order_number])).status_code, 405)
        other = make_user(username='other', email='other@example.com')
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('order_pay_on_delivery', args=[order.order_number])).status_code, 404)

    def test_pay_options_are_hidden_while_a_prompt_is_pending(self):
        self.client.force_login(self.user)
        order = self._order(payment_method=Order.PAYMENT_MPESA)
        for name in ('order-success', 'order_detail'):
            page = self.client.get(reverse(name, args=[order.order_number]))
            self.assertContains(page, 'class="pay-options mt-3 hidden"')
            self.assertContains(page, 'Cancel order')

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
        # The product card shows the unit as "per dozen", never the short code.
        self.assertContains(response, 'per dozen')
        self.assertNotContains(response, 'dzn')

    def test_navigation_cache_is_invalidated_when_catalogue_changes(self):
        from django.core.cache import cache
        cache.clear()
        # Names the home hero's static rings do not use, so they can only come from the nav.
        make_product(name="One", item_code="C1", category_name="Spices")
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Spices')
        make_product(name="Two", item_code="C2", category_name="Stationery")
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Stationery')
        Category.objects.filter(name='Stationery').delete()
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'Stationery')

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
        # A line without a wholesale price is charged at retail, so its retail reduction
        # is a real offer for a wholesaler too.
        self.assertEqual(set(Product.objects.on_offer('wholesale')), {self.both, self.retail_only})
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
        # "Both Tiers" has no wholesale reduction yet; "Retail Only" is charged (and reduced) at retail.
        response = self.client.get(reverse('offers'))
        self.assertEqual([p.name for p in response.context['products']], ["Retail Only"])
        self.both.old_wholesale_price = Decimal('1000')
        self.both.save()
        self.assertEqual(self.client.get(reverse('offers')).context['total_count'], 2)


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


class PriceListTests(TestCase):
    def test_csv_is_generated_from_live_catalogue(self):
        make_product(name="Golden Fry Cooking Oil 3L", item_code="OIL1", retail="1050", wholesale="900", old="1100")
        make_product(name="Hidden", item_code="H1", is_active=False)
        response = self.client.get(reverse('price_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        body = response.content.decode('utf-8')
        self.assertIn("Golden Fry Cooking Oil 3L", body)
        self.assertIn("1050.00,900.00,1100.00,,16,yes", body)
        self.assertNotIn("Hidden", body)


class CouponAndVatTests(TestCase):
    """Coupons take a percentage off the order; prices include VAT at each product's rate."""

    def setUp(self):
        cache.clear()
        self.oil = make_product()                                    # 16% VAT, KSh 1,050
        self.flour = make_product(name="Maize Flour 2kg", item_code="FL1", retail="200", wholesale=None, old=None,
                                  vat_rate=Decimal('0'))            # zero-rated
        self.coupon = Coupon.objects.create(code='karibu10', percent=Decimal('10'))
        self.user = make_user()
        self.client.force_login(self.user)
        self.client.post(reverse('cart_add'), {'product_id': self.oil.id, 'product_qty': 2})    # 2,100
        self.client.post(reverse('cart_add'), {'product_id': self.flour.id, 'product_qty': 5})  # 1,000

    def _apply(self, **data):
        return self.client.post(reverse('apply_coupon'), data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def _place(self):
        payload = {'first_name': 'Jane', 'last_name': 'Doe', 'email': 'shop@example.com', 'phone': '0712345678',
                   'address': 'Baba Dogo Rd', 'city': 'Nairobi', 'payment_method': 'cod'}
        return self.client.post(reverse('place-order'), data=json.dumps(payload), content_type='application/json')

    def test_vat_is_worked_out_per_line(self):
        cart = self.client.get(reverse('shopping-cart')).context['cart']
        self.assertEqual(cart.subtotal, Decimal('3100'))
        self.assertEqual(cart.vat, Decimal('289.66'))    # 2,100 x 16/116; the flour carries none
        self.assertEqual(cart.net, Decimal('2810.34'))
        self.assertEqual(cart.total, Decimal('3100'))

    def test_coupon_is_stored_upper_case_and_applies_any_case(self):
        self.assertEqual(self.coupon.code, 'KARIBU10')
        data = self._apply(code=' Karibu10 ').json()
        self.assertTrue(data['ok'], data)
        self.assertEqual(data['cart']['subtotal'], 3100.0)
        self.assertEqual(data['cart']['discount'], 310.0)
        self.assertEqual(data['cart']['total'], 2790.0)
        self.assertEqual(data['cart']['vat'], 260.69)    # the coupon lowers the VAT by the same share
        self.assertEqual(data['cart']['coupon'], 'KARIBU10')
        page = self.client.get(reverse('shopping-cart'))
        self.assertContains(page, 'KARIBU10')
        self.assertContains(page, 'KSh 2,790')

    def test_invalid_expired_and_inactive_codes_are_refused(self):
        import datetime
        self.assertEqual(self._apply(code='NOPE').status_code, 400)
        self.assertEqual(self._apply(code='').status_code, 400)
        Coupon.objects.create(code='OLD5', percent=5, valid_until=datetime.date(2020, 1, 1))
        Coupon.objects.create(code='OFF5', percent=5, active=False)
        self.assertEqual(self._apply(code='OLD5').status_code, 400)
        self.assertEqual(self._apply(code='OFF5').status_code, 400)
        self.assertEqual(self.client.get(reverse('shopping-cart')).context['cart'].discount, Decimal('0'))

    def test_coupon_can_be_removed_and_falls_away_when_switched_off(self):
        self._apply(code='KARIBU10')
        self.assertEqual(self._apply(remove='1').json()['cart']['discount'], 0)
        self._apply(code='KARIBU10')
        Coupon.objects.filter(pk=self.coupon.pk).update(active=False)
        self.assertEqual(self.client.get(reverse('shopping-cart')).context['cart'].total, Decimal('3100'))

    def test_coupon_form_works_without_javascript(self):
        res = self.client.post(reverse('apply_coupon'), {'code': 'KARIBU10'}, HTTP_REFERER='http://testserver/shopping-cart/')
        self.assertEqual(res.url, 'http://testserver/shopping-cart/')
        self.assertEqual(self.client.get(reverse('shopping-cart')).context['cart'].discount, Decimal('310'))
        res = self.client.post(reverse('apply_coupon'), {'code': 'KARIBU10'}, HTTP_REFERER='https://evil.example/x')
        self.assertRedirects(res, reverse('shopping-cart'))  # never redirected off-site

    def test_order_records_discount_and_vat_and_uses_the_coupon_once(self):
        self._apply(code='KARIBU10')
        data = self._place().json()
        self.assertTrue(data['ok'], data)
        order = Order.objects.get(order_number=data['order_number'])
        self.assertEqual(order.total_amount, Decimal('2790'))
        self.assertEqual(order.discount_amount, Decimal('310'))
        self.assertEqual(order.discount_percent, Decimal('10'))
        self.assertEqual(order.coupon_code, 'KARIBU10')
        self.assertEqual(order.vat_amount, Decimal('260.69'))
        self.assertEqual(order.net_amount, Decimal('2529.31'))
        self.assertEqual(order.subtotal_amount, Decimal('3100'))
        self.assertNotIn('coupon', self.client.session)
        page = self.client.get(order.get_absolute_url())
        self.assertContains(page, 'Discount (KARIBU10, 10%)')
        self.assertContains(page, 'VAT (included)')

    def test_promoted_coupon_is_advertised(self):
        self.assertNotContains(self.client.get(reverse('products')), 'id="promoModal"')
        self.coupon.promote = True
        self.coupon.save()
        response = self.client.get(reverse('products'))
        self.assertContains(response, 'id="promoModal"')
        self.assertContains(response, '10% OFF')

    def test_order_pdf_is_private_and_a_real_pdf(self):
        self._apply(code='KARIBU10')
        order = Order.objects.get(order_number=self._place().json()['order_number'])
        res = self.client.get(reverse('order_pdf', args=[order.order_number]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/pdf')
        self.assertTrue(res.content.startswith(b'%PDF'))
        self.assertIn(order.order_number, res['Content-Disposition'])
        self.client.force_login(make_user(username='other', email='other@example.com'))
        self.assertEqual(self.client.get(reverse('order_pdf', args=[order.order_number])).status_code, 404)


class StockTests(TestCase):
    """Stock status on the storefront and what it allows a customer to order."""

    def setUp(self):
        cache.clear()
        self.product = make_product()
        self.user = make_user()
        self.client.force_login(self.user)
        self.payload = {'first_name': 'Jane', 'last_name': 'Doe', 'email': 'shop@example.com', 'phone': '0712345678',
                        'address': 'Baba Dogo Rd', 'city': 'Nairobi', 'payment_method': 'cod'}

    def _add(self, qty, product=None):
        return self.client.post(reverse('cart_add'), {'product_id': (product or self.product).id, 'product_qty': qty},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def _place(self):
        return self.client.post(reverse('place-order'), data=json.dumps(self.payload), content_type='application/json')

    @override_settings(LOW_STOCK_THRESHOLD=5)
    def test_stock_states(self):
        self.assertEqual(self.product.stock_state, '')          # nothing received yet: not tracked
        self.assertIsNone(self.product.available_stock)
        add_stock(self.product, 20)
        self.assertEqual(self.product.stock_state, 'in')
        StockLedger.objects.create(product=self.product, transaction_type='SALE', quantity=-16)
        self.assertEqual(self.product.stock_state, 'low')
        self.assertEqual(self.product.available_stock, 4)
        StockLedger.objects.create(product=self.product, transaction_type='SALE', quantity=-4)
        self.assertEqual(self.product.stock_state, 'out')
        self.assertFalse(self.product.in_stock)
        annotated = Product.objects.with_stock().get(pk=self.product.pk)
        with self.assertNumQueries(0):
            self.assertEqual(annotated.stock_state, 'out')

    def test_catalogue_shows_badges_without_a_query_per_product(self):
        def queries_for(count):
            for index in range(count):
                add_stock(make_product(name=f"Line {count}-{index}", item_code=f"L{count}-{index}"), 50)
            cache.clear()
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('products'))
            self.assertContains(response, 'stock-in')
            return len(queries)

        queries_for(1)  # the first page view also sets up the session
        self.assertEqual(queries_for(2), queries_for(9))

    def test_out_of_stock_cannot_be_added_and_quantity_is_capped(self):
        add_stock(self.product, 3)
        res = self._add(5)
        self.assertTrue(res.json()['ok'])
        self.assertEqual(res.json()['product']['qty'], 3)
        self.assertIn('Only 3', res.json()['message'])
        self.assertEqual(self._add(1).status_code, 400)        # already holding everything there is
        StockLedger.objects.create(product=self.product, transaction_type='SALE', quantity=-3)
        self.client.post(reverse('cart_delete'), {'product_id': self.product.id})
        res = self._add(1)
        self.assertEqual(res.status_code, 400)
        self.assertIn('out of stock', res.json()['error'])
        self.assertContains(self.client.get(self.product.get_absolute_url()), 'Out of stock')

    def test_cart_update_is_capped_and_json_zero_removes_the_line(self):
        add_stock(self.product, 4)
        self._add(1)
        res = self.client.post(reverse('cart_update'), data=json.dumps({'product_id': self.product.id, 'product_qty': 9}),
                               content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.json()['item_qty'], 4)
        # The storefront sends JSON; a quantity of 0 must remove the line, not become 1.
        res = self.client.post(reverse('cart_update'), data=json.dumps({'product_id': self.product.id, 'product_qty': 0}),
                               content_type='application/json', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.json()['item_qty'], 0)
        self.assertEqual(self.client.session['cart'], {})

    def test_checkout_books_stock_and_refuses_what_is_no_longer_there(self):
        add_stock(self.product, 5)
        self._add(4)
        data = self._place().json()
        self.assertTrue(data['ok'], data)
        self.assertEqual(self.product.current_stock, 1)         # held from the moment the order is placed
        # A second customer still has 4 in a cart filled earlier.
        session = self.client.session
        session['cart'] = {str(self.product.id): 4}
        session.save()
        res = self._place()
        self.assertEqual(res.status_code, 400)
        self.assertIn('Only 1', res.json()['error'])
        self.assertEqual(Order.objects.count(), 1)
        self.assertContains(self.client.get(reverse('checkout')), 'Only 1')
        # Cancelling the first order frees its stock again.
        self.client.post(reverse('order_cancel', args=[data['order_number']]))
        self.assertEqual(self.product.current_stock, 5)

    def test_unpriced_products_cannot_be_bought(self):
        free = make_product(name="No Price Yet", item_code="NP1", retail=None, wholesale=None, old=None)
        Product.objects.filter(pk=free.pk).update(retail_price=None)
        res = self._add(1, free)
        self.assertEqual(res.status_code, 400)
        self.assertIn('no price', res.json()['error'])


class CheckoutAndAccountFixTests(TestCase):
    """Behaviour fixed in the 2026-10-01 backend review."""

    def setUp(self):
        cache.clear()
        self.product = make_product()
        self.user = make_user()
        self.client.force_login(self.user)
        self.payload = {'first_name': 'Jane', 'last_name': 'Doe', 'email': 'shop@example.com', 'phone': '0712345678',
                        'address': 'New Depot, Mombasa Rd', 'city': 'Nairobi', 'payment_method': 'cod', 'save_address': True}

    def _order(self):
        self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 1})
        return self.client.post(reverse('place-order'), data=json.dumps(self.payload), content_type='application/json').json()

    def test_checkout_adds_an_address_instead_of_overwriting_the_primary_one(self):
        profile = self.user.customerprofile
        Address.objects.create(customer=profile, label='Main shop', physical_address='Moi Avenue', city='Nairobi', is_primary=True)
        self.assertTrue(self._order()['ok'])
        self.assertEqual(profile.addresses.count(), 2)
        self.assertEqual(profile.addresses.get(is_primary=True).physical_address, 'Moi Avenue')
        self._order()  # the same address again is not saved twice
        self.assertEqual(profile.addresses.count(), 2)

    def test_stale_cart_lines_do_not_reach_checkout(self):
        self.client.post(reverse('cart_add'), {'product_id': self.product.id, 'product_qty': 1})
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertRedirects(self.client.get(reverse('checkout')), reverse('products'))
        res = self.client.post(reverse('place-order'), data=json.dumps(self.payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_shop_copy_of_the_confirmation_is_a_blind_copy(self):
        from django.core import mail
        with override_settings(ORDER_NOTIFICATION_EMAIL='orders@mahitaji.example'):
            self._order()
        self.assertEqual(mail.outbox[0].to, ['shop@example.com'])
        self.assertEqual(mail.outbox[0].bcc, ['orders@mahitaji.example'])
        self.assertIn('VAT (included)', mail.outbox[0].body)

    def test_long_product_names_get_a_slug_that_fits(self):
        name = "Extra Virgin Sunflower Cooking Oil Family Economy Refill Pack 20 Litres"
        a = make_product(name=name, item_code="LONG1")
        b = make_product(name=name, item_code="LONG2")
        limit = Product._meta.get_field('slug').max_length
        self.assertLessEqual(len(a.slug), limit)
        self.assertLessEqual(len(b.slug), limit)
        self.assertNotEqual(a.slug, b.slug)

    def test_sign_in_is_paused_after_repeated_failures_and_logout_needs_post(self):
        self.client.logout()
        for _ in range(8):
            res = self.client.post(reverse('login'), {'username': 'shop@example.com', 'password': 'wrong'},
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(res.status_code, 400)
        res = self.client.post(reverse('login'), {'username': 'shop@example.com', 'password': 'Str0ngPass!42'},
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 429)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)

    def test_json_endpoints_survive_a_non_object_body(self):
        res = self.client.post(reverse('cart_add'), data='[1, 2, 3]', content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_wholesale_price_sort_falls_back_to_retail(self):
        make_product(name="Cheap Retail Only", item_code="CR1", retail="100", wholesale=None, old=None)
        make_product(name="Dear Wholesale", item_code="DW1", retail="5000", wholesale="4000", old=None)
        self.client.force_login(make_user(username='ws', email='ws@example.com', wholesaler=True))
        names = [p.name for p in self.client.get(reverse('products') + '?sort=price_asc').context['products']]
        self.assertEqual(names.index("Cheap Retail Only"), 0)
        self.assertLess(names.index("Golden Fry Cooking Oil 3L"), names.index("Dear Wholesale"))


class HardeningTests(TestCase):
    """Rate limits, staff session expiry, background email and the order-expiry command."""

    def setUp(self):
        cache.clear()
        self.product = make_product()

    def _login(self, username, password, ip='203.0.113.5'):
        return self.client.post(reverse('login'), {'username': username, 'password': password},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest', REMOTE_ADDR=ip)

    def test_an_address_spraying_many_accounts_is_paused(self):
        for n in range(30):
            self.assertEqual(self._login(f'victim{n}@example.com', 'wrong').status_code, 400)
        self.assertEqual(self._login('someone-else@example.com', 'wrong').status_code, 429)
        self.assertEqual(self._login('someone-else@example.com', 'wrong', ip='198.51.100.9').status_code, 400)

    def test_forwarded_address_is_ignored_unless_behind_our_proxy(self):
        with override_settings(TRUST_X_FORWARDED_FOR=False):
            for n in range(8):   # spoofing a different address each time must not reset the count
                self.client.post(reverse('login'), {'username': 'shop@example.com', 'password': 'wrong'},
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_X_FORWARDED_FOR=f'10.0.0.{n}')
            res = self.client.post(reverse('login'), {'username': 'shop@example.com', 'password': 'wrong'},
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_X_FORWARDED_FOR='10.0.0.99')
            self.assertEqual(res.status_code, 429)

    def test_registration_and_password_reset_are_rate_limited(self):
        form = {'first_name': 'A', 'last_name': 'B', 'phone_number': '0712345678', 'password': 'Str0ngPass!42', 'confirm_password': 'Str0ngPass!42'}
        for n in range(10):
            res = self.client.post(reverse('register'), {**form, 'email': f'new{n}@example.com'},
                                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(res.status_code, 200, res.content[:200])
            self.client.logout()
        res = self.client.post(reverse('register'), {**form, 'email': 'new99@example.com'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 429)
        self.assertFalse(User.objects.filter(email='new99@example.com').exists())

        from django.core import mail
        make_user()
        for _ in range(5):
            self.assertEqual(self.client.post(reverse('password_reset'), {'email': 'shop@example.com'},
                                              HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 200)
        self.assertEqual(self.client.post(reverse('password_reset'), {'email': 'shop@example.com'},
                                          HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 429)
        self.assertEqual(len(mail.outbox), 5)

    @override_settings(STAFF_SESSION_IDLE_SECONDS=3600)
    def test_staff_are_signed_out_after_idling_but_customers_are_not(self):
        from core.middleware import SEEN_KEY
        staff = User.objects.create_user('staff', 'staff@example.com', 'Str0ngPass!42', is_staff=True)
        self.client.force_login(staff)
        self.client.get(reverse('home'))
        session = self.client.session
        session[SEEN_KEY] = int(session[SEEN_KEY]) - 7200   # last seen two hours ago
        session.save()
        self.client.get(reverse('home'))
        self.assertFalse(self.client.session.get('_auth_user_id'))
        customer = make_user()
        self.client.force_login(customer)
        self.client.get(reverse('home'))
        self.assertNotIn(SEEN_KEY, self.client.session)
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_api_has_no_basic_auth_and_is_throttled(self):
        import base64
        user = make_user()
        creds = base64.b64encode(b'shop@example.com:Str0ngPass!42').decode()
        res = self.client.get('/data/orders/', HTTP_AUTHORIZATION=f'Basic {creds}')
        self.assertEqual(res.status_code, 403)          # credentials in a header are ignored
        for _ in range(60):
            self.assertEqual(self.client.get('/data/products/').status_code, 200)
        self.assertEqual(self.client.get('/data/products/').status_code, 429)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/data/orders/').status_code, 200)

    def test_admin_path_comes_from_settings(self):
        from django.urls import reverse as rev
        self.assertEqual(rev('admin:index'), '/' + settings.ADMIN_URL)

    def test_order_confirmation_is_sent_in_the_background_when_configured(self):
        from django.core import mail
        from core import mailer
        from django.core.mail import EmailMessage
        with override_settings(EMAIL_IN_BACKGROUND=True):
            mailer.send(EmailMessage('Hi', 'body', 'a@example.com', ['b@example.com']), label='test')
            import threading
            for thread in threading.enumerate():
                if thread.name.startswith('email:'):
                    thread.join(5)
        self.assertEqual(len(mail.outbox), 1)

    def test_expire_unpaid_orders_cancels_old_mpesa_orders_only(self):
        from io import StringIO
        from django.core.management import call_command
        add_stock(self.product, 10)
        user = make_user()
        def order(method, status, age_hours):
            o = Order.objects.create(customer=user.customerprofile, payment_method=method, status=status,
                                     total_amount=Decimal('1050'), full_name='J', phone='254712345678')
            OrderItem.objects.create(order=o, product=self.product, quantity=1, price_at_purchase=Decimal('1050'))
            sync_order_stock(o)
            Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(hours=age_hours))
            return o
        old_failed = order(Order.PAYMENT_MPESA, Order.STATUS_FAILED, 30)
        old_pending = order(Order.PAYMENT_MPESA, Order.STATUS_PENDING, 25)
        fresh = order(Order.PAYMENT_MPESA, Order.STATUS_PENDING, 2)
        cod = order(Order.PAYMENT_COD, Order.STATUS_PENDING, 90)
        paid = order(Order.PAYMENT_MPESA, Order.STATUS_PAID, 90)
        self.assertEqual(self.product.current_stock, 5)
        out = StringIO()
        call_command('expire_unpaid_orders', '--dry-run', stdout=out)
        self.assertIn('would cancel 2', out.getvalue())
        self.assertEqual(Order.objects.filter(status=Order.STATUS_CANCELLED).count(), 0)
        call_command('expire_unpaid_orders', stdout=out)
        for o in (old_failed, old_pending, fresh, cod, paid):
            o.refresh_from_db()
        self.assertEqual([o.status for o in (old_failed, old_pending)], ['CANCELLED', 'CANCELLED'])
        self.assertEqual([fresh.status, cod.status, paid.status], ['PENDING', 'PENDING', 'PAID'])
        self.assertEqual(self.product.current_stock, 7)   # the two cancelled orders gave their units back


def png_bytes(size=(40, 40), colour=(200, 30, 30)):
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new('RGB', size, colour).save(out, 'PNG')
    return out.getvalue()


class ProductImageImportTests(TestCase):
    """Bulk photo upload in the admin and the ``image`` column of a product CSV."""

    def setUp(self):
        import tempfile
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(lambda: __import__('shutil').rmtree(self.media, ignore_errors=True))
        self.product = make_product()                       # BD001
        self.other = make_product(name="Sunflower Oil 1L", item_code="BD002")
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ngPass!42')
        self.client.force_login(self.admin)
        self.url = reverse('admin:core_product_upload_images')

    def _upload(self, files, replace=True):
        from django.core.files.uploadedfile import SimpleUploadedFile
        uploads = [SimpleUploadedFile(name, data) for name, data in files]
        data = {'files': uploads}
        if replace:
            data['replace_existing'] = '1'
        return self.client.post(self.url, data)

    def test_upload_button_and_page_are_staff_only(self):
        self.assertContains(self.client.get(reverse('admin:core_product_changelist')), self.url)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_files_named_after_item_codes_are_attached(self):
        import os
        res = self._upload([('bd001.png', png_bytes()), ('BD002_front.png', png_bytes()), ('loose-shot.png', png_bytes()),
                            ('notes.png', b'this is not an image'), ('readme.txt', b'hi')])
        self.assertEqual(res.status_code, 200)
        self.product.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(self.product.image.name, 'products/bd001.png')
        self.assertEqual(self.other.image.name, 'products/BD002_front.png')
        self.assertTrue(os.path.exists(os.path.join(self.media, 'products', 'loose-shot.png')))
        self.assertFalse(os.path.exists(os.path.join(self.media, 'products', 'notes.png')))
        self.assertContains(res, 'loose-shot.png')                 # saved, listed as unmatched
        self.assertContains(res, 'notes.png: not a valid image')
        self.assertContains(res, 'readme.txt: not a .jpg')

    def test_zip_archives_are_unpacked_and_existing_photos_can_be_kept(self):
        import io, zipfile
        self.product.image.name = 'products/old.png'
        self.product.save()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('photos/bd001.png', png_bytes())
            archive.writestr('photos/bd002.png', png_bytes())
            archive.writestr('__MACOSX/._bd001.png', b'junk')
        res = self._upload([('photos.zip', buffer.getvalue())], replace=False)
        self.product.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(self.product.image.name, 'products/old.png')   # kept: replace unticked
        self.assertEqual(self.other.image.name, 'products/bd002.png')
        self.assertContains(res, 'Already had a photo')

    def test_large_photos_are_shrunk(self):
        from PIL import Image
        import os
        self._upload([('bd001.png', png_bytes(size=(4000, 3000)))])
        with Image.open(os.path.join(self.media, 'products', 'bd001.png')) as image:
            self.assertEqual(image.size, (1600, 1200))

    def test_csv_import_links_files_downloads_urls_and_keeps_blank_cells(self):
        import tablib
        from core.resources import ProductResource
        from core import images
        images.store('shelf.png', png_bytes())
        self.other.image.name = 'products/keep.png'
        self.other.save()
        fake = mock.Mock(status_code=200, headers={'Content-Type': 'image/png'})
        fake.iter_content = lambda n: [png_bytes(colour=(0, 0, 200))]
        fake.raise_for_status = lambda: None
        fake.__enter__ = lambda self_: self_
        fake.__exit__ = lambda *a: False
        dataset = tablib.Dataset(headers=['item_code', 'name', 'image'])
        dataset.append(['BD001', 'Golden Fry Cooking Oil 3L', 'shelf.png'])
        dataset.append(['BD002', 'Sunflower Oil 1L', ''])
        dataset.append(['BD003', 'Brand New Soap', 'https://cdn.example.com/photos/soap.png'])
        with mock.patch('core.images.requests.get', return_value=fake) as get:
            result = ProductResource().import_data(dataset, dry_run=False, raise_errors=True)
        self.assertFalse(result.has_errors())
        get.assert_called_once()
        self.product.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(self.product.image.name, 'products/shelf.png')
        self.assertEqual(self.other.image.name, 'products/keep.png')         # blank cell: untouched
        self.assertEqual(Product.objects.get(item_code='BD003').image.name, 'products/BD003.png')

    def test_csv_import_reports_a_missing_image_file(self):
        import tablib
        from core.resources import ProductResource
        dataset = tablib.Dataset(headers=['item_code', 'name', 'image'])
        dataset.append(['BD001', 'Golden Fry Cooking Oil 3L', 'nowhere.jpg'])
        result = ProductResource().import_data(dataset, dry_run=True)
        self.assertTrue(result.has_errors() or result.has_validation_errors())
        text = str([e.error for row in result.row_errors() for e in row[1]] + [str(r.error_dict) for r in result.invalid_rows])
        self.assertIn('nowhere.jpg', text)
        self.product.refresh_from_db()
        self.assertFalse(self.product.image)

    def test_export_includes_the_image_path(self):
        from core.resources import ProductResource
        self.product.image.name = 'products/bd001.png'
        self.product.save()
        exported = ProductResource().export(Product.objects.filter(pk=self.product.pk))
        self.assertIn('image', exported.headers)
        self.assertEqual(exported.dict[0]['image'], 'products/bd001.png')
