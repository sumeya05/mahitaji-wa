# Mahitaji E-commerce Platform

A wholesale and retail e-commerce storefront for **Mahitaji Enterprises Ltd**, a fast-moving consumer goods (FMCG) distributor in Nairobi, Kenya. Built with Django 5.2 and a hand-written, dependency-free front end.

## Features

- **Catalogue** with category and brand filters, full-text search with live suggestions, sorting, AJAX pagination and an offers page.
- **Two price tiers** (retail / wholesale) resolved from the customer's account; the cart is always charged at the account's tier.
- **Session cart** with slide-out drawer, quantity steppers and live totals; survives login.
- **Checkout** with saved addresses, cash on delivery or **M-Pesa STK push** (Safaricom Daraja) including callback handling, payment polling, retry and order status timeline.
- **Customer account**: dashboard, order history with detail modal, addresses, M-Pesa number, profile & password settings, wishlist.
- **Stock ledger** that deducts stock when an order is paid and restocks on cancellation (idempotent).
- **Contact form**, newsletter signup, AI shopping assistant (Gemini, with a catalogue-search fallback when no API key is set).
- **Admin**: import/export for products, categories, brands, suppliers and stock; order status actions.
- Read-only JSON API at `/data/` (products, categories, brands, and the signed-in customer's orders).

## Tech stack

- Python 3.11, Django 5.2, Django REST Framework, django-import-export, django-daraja
- MySQL (production) / SQLite (tests and optional local development)
- Front end: one stylesheet (`static/css/mahitaji.css`) and one script (`static/js/mahitaji.js`), Font Awesome 6, Google Fonts. No build step.
- WhiteNoise for static files, Gunicorn for serving.

## Getting started

```bash
# 1. Environment
python -m venv venv && source venv/bin/activate      # or: conda env create -f mahitaji-env.yml
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env                                  # then edit the values
# Set USE_SQLITE=true in .env if you do not have MySQL locally.

# 3. Database & admin user
python manage.py migrate
python manage.py createsuperuser

# 4. Run
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the shop and http://127.0.0.1:8000/admin/ for administration.

### Loading products

Use **Admin → Products → Import** with a CSV that has the columns
`item_code, name, category, brand, supplier, uom, old_price, retail_price, old_wholesale_price, wholesale_price, is_active, is_trending, is_best_seller`
(`old_price` / `old_wholesale_price` are the previous prices; a product is on offer for a tier when its previous price is higher than the current one)
(categories, brands, suppliers and units are matched by name). Opening stock can be imported into **Stock Ledger** with `item_code, transaction_type, quantity, reference_number`.

If product photos are already in `media/products/`, link them to image-less products by filename:

```bash
python manage.py link_product_images          # dry run
python manage.py link_product_images --apply
```

### M-Pesa

1. Create a sandbox app at https://developer.safaricom.co.ke and copy the consumer key, secret and passkey into `.env`.
2. Expose your dev server over HTTPS (for example with ngrok) and set `MPESA_CALLBACK_URL=https://<your-host>/mpesa/callback/`.
3. Add the ngrok host to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

Until `MPESA_CALLBACK_URL` is set, checkout still works: M-Pesa orders are created as *Pending* and customers can retry the prompt from the order page.

## Tests

```bash
python manage.py test core
```

The test-suite runs on an in-memory SQLite database, so it needs no MySQL privileges.

## Deployment checklist

- `DEBUG=False`, a strong `SECRET_KEY`, real `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- `python manage.py collectstatic` (WhiteNoise serves the compressed files).
- SMTP settings for order confirmations, or keep the console backend if email is not needed.
- Run with `gunicorn ecommerce.wsgi` behind an HTTPS proxy; the settings enable HSTS and secure cookies automatically when `DEBUG` is off.

## Project layout

```
core/                 # models, views, forms, cart, M-Pesa services, signals, admin, API
core/templatetags/    # {% load shop %}: money formatting, tier pricing, badges
core/management/      # link_product_images
templates/base/       # base layout (header, footer, cart drawer, assistant)
templates/partials/   # product card/grid, pagination, filters, hero
templates/core/       # storefront, auth/, account/, pages/, emails/
static/css|js         # mahitaji.css, mahitaji.js
```
