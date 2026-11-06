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
- **Mahitaji Fleet**: logistics masters (vehicles, drivers and turnboys, areas and routes, delivery customers) and the
  **Mahitaji Fleet app** for Android and iOS in [`mahitaji-fleet/`](mahitaji-fleet/README.md) (Expo / React Native).

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
`item_code, name, category, brand, supplier, uom, old_retail_price, retail_price, old_wholesale_price, wholesale_price, is_active, is_trending, is_best_seller`
(`old_retail_price` / `old_wholesale_price` are the previous prices; a product is on offer for a tier when its previous price is higher than the current one)
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

## Mahitaji Fleet

### Masters

The `fleet` app holds the logistics masters, all under **Admin → Fleet** with CSV import/export
(related records are matched by code, not id):

| Master | Fields | Import key |
|---|---|---|
| Company | code, name | `code` |
| Employee | code, name, **role** (Driver / Turnboy / Other staff), company, phone | `employee_code` |
| Route | code, name, company | `code` |
| Area | code, name, route, company, county, town, description | `code` |
| Vehicle | vehicle number, type, capacity (kg), company, driver, turnboy | `registration_number` |

Drivers and turnboys are ordinary employees told apart by their role. A vehicle's driver must have the
Driver role and its turnboy the Turnboy role, and each is on one vehicle at a time. An area's route
must belong to the same company.

The **customer master** is the shop's own customer list (**Admin → Core → Customer profiles**). Each
customer has a customer code (assigned as `MC00042` when left blank), an area (which gives the route), a
GPS location, contact details and addresses. Staff can add delivery customers who have no shop login, and
import them with the columns `customer_code, business_name, contact_person, phone_number, tax_id,
is_wholesaler, erp_id, area, latitude, longitude, address, city`.

### The app

The Expo app in [`mahitaji-fleet/`](mahitaji-fleet/README.md) is for logistics staff: browse and search the
masters, add and edit them, call drivers and customers, and record a customer's GPS location from the
phone. It uses the API in `fleet/api.py` at `/api/v1/fleet/` with token sign-in (`auth/login/`).

Access follows the admin's permissions: put staff in a group (for example *Logistics*) with the *view*,
*add* and *change* permissions for the masters they work with. A tab is shown only to people who can view
that master; Add and Edit only to those who can add or change. Shop customers have no such permissions
and cannot sign in. Companies are read-only in the app.

To try it locally, run `./run-app.sh` (sample data from `python manage.py seed_fleet_demo`; sign in as
`fleet@example.com` / `Fleet2026!secure`). See `mahitaji-fleet/README.md` for phones and store builds.

The shop's earlier mobile API (`core/views/mobile.py`, at `/api/v1/`) is still served, but no app in this
repository uses it any more.

## Tests

```bash
python manage.py test core fleet
```

The test-suite runs on an in-memory SQLite database, so it needs no MySQL privileges.

## Deployment

Everything needed for an Ubuntu + MySQL + Redis + Gunicorn + Nginx server is in [`deploy/`](deploy/README.md):
a step-by-step runbook, the Nginx and systemd units, Gunicorn and MySQL tuning, backup and
maintenance timers, and a hardening script (firewall, fail2ban, SSH, automatic updates).

In short: `DEBUG=False`, a strong `SECRET_KEY`, real `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`,
`REDIS_URL`, `ADMINS`, an unguessable `ADMIN_URL`, SMTP settings, production M-Pesa credentials;
then `collectstatic`, `migrate` and `python manage.py check --deploy`.

## Project layout

```
core/                 # models, views, forms, cart, M-Pesa services, signals, admin, API
core/templatetags/    # {% load shop %}: money formatting, tier pricing, badges
core/management/      # link_product_images
fleet/                # Mahitaji Fleet masters and the app's API at /api/v1/fleet/
mahitaji-fleet/       # Mahitaji Fleet app (Expo / React Native)
templates/base/       # base layout (header, footer, cart drawer, assistant)
templates/partials/   # product card/grid, pagination, filters, hero
templates/core/       # storefront, auth/, account/, pages/, emails/
static/css|js         # mahitaji.css, mahitaji.js
```
