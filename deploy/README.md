# Deploying Mahitaji

Target: one Ubuntu 22.04/24.04 VPS (2 vCPU, 4 GB) running MySQL 8, Redis, Gunicorn and Nginx,
with TLS from Let's Encrypt. Everything referenced here lives in this folder. Paths assume the
app is checked out at `/srv/mahitaji/app` with a virtualenv at `/srv/mahitaji/venv`.

Memory budget on 4 GB: MySQL ~900 MB, Gunicorn ~400 MB (capped at 1.5 GB), Redis ≤128 MB,
Nginx + OS ~300 MB, ~1 GB free, 2 GB swap as a safety net.

## 1. Harden the box (as root, once)

```bash
# add your SSH public key to ~/.ssh/authorized_keys first
bash deploy/scripts/harden.sh      # ufw (22/80/443 only), fail2ban, SSH keys only, auto security updates, 2 GB swap
```

## 2. Packages

```bash
apt install -y python3-venv python3-dev build-essential pkg-config default-libmysqlclient-dev \
               mysql-server redis-server nginx certbot python3-certbot-nginx git rclone
```

## 3. MySQL

```bash
mysql_secure_installation
cp deploy/mysql/99-mahitaji.cnf /etc/mysql/mysql.conf.d/ && systemctl restart mysql
mysql -e "CREATE DATABASE mahitaji_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
          CREATE USER 'mahitaji'@'localhost' IDENTIFIED BY '<long random password>';
          GRANT ALL ON mahitaji_db.* TO 'mahitaji'@'localhost'; FLUSH PRIVILEGES;"
```

## 4. Redis

Append `deploy/redis/99-mahitaji.conf` to `/etc/redis/redis.conf` (or adjust those keys), then
`systemctl restart redis-server`. Check: `redis-cli ping` → `PONG`.

## 5. The app

```bash
adduser --system --group --home /srv/mahitaji mahitaji
usermod -aG www-data mahitaji
sudo -u mahitaji git clone <repo> /srv/mahitaji/app
sudo -u mahitaji python3 -m venv /srv/mahitaji/venv
sudo -u mahitaji /srv/mahitaji/venv/bin/pip install -r /srv/mahitaji/app/requirements.txt
cp /srv/mahitaji/app/.env.example /srv/mahitaji/app/.env && chmod 600 /srv/mahitaji/app/.env
chown mahitaji:www-data /srv/mahitaji/app/.env
```

Fill in `.env`. The production-critical values:

| Key | Value |
| --- | --- |
| `DEBUG` | `false` |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` — never change it afterwards (sessions, reset links and the M-Pesa callback URL depend on it) |
| `ALLOWED_HOSTS` | `mahitaji.co.ke,www.mahitaji.co.ke` |
| `CSRF_TRUSTED_ORIGINS` | `https://mahitaji.co.ke,https://www.mahitaji.co.ke` |
| `DB_*` | the MySQL user above, `DB_HOST=127.0.0.1` |
| `REDIS_URL` | `redis://127.0.0.1:6379/1` |
| `ADMIN_URL` | something unguessable, e.g. `office-7f3k/` |
| `ADMINS` | `Ian:you@example.com` (server errors are emailed here) |
| `EMAIL_*` | a transactional SMTP provider; `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` |
| `MPESA_*` | production Daraja credentials, `MPESA_ENVIRONMENT=production`, `MPESA_CALLBACK_URL=https://mahitaji.co.ke/mpesa/callback/` |

Then:

```bash
cd /srv/mahitaji/app
sudo -u mahitaji /srv/mahitaji/venv/bin/python manage.py check --deploy
sudo -u mahitaji /srv/mahitaji/venv/bin/python manage.py migrate
sudo -u mahitaji /srv/mahitaji/venv/bin/python manage.py collectstatic --noinput
sudo -u mahitaji /srv/mahitaji/venv/bin/python manage.py createsuperuser
mkdir -p media && chown -R mahitaji:www-data media && chmod -R u=rwX,g=rX,o= media
```

## 6. Gunicorn (systemd)

```bash
cp deploy/systemd/mahitaji.socket deploy/systemd/mahitaji.service /etc/systemd/system/
cp deploy/systemd/mahitaji-maintenance.* deploy/systemd/mahitaji-backup.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mahitaji.socket mahitaji.service mahitaji-maintenance.timer mahitaji-backup.timer
systemctl status mahitaji --no-pager
```

`mahitaji.service` runs `deploy/gunicorn.conf.py` (2 workers × 4 threads, 30 s timeout, worker
recycling, 1.5 GB memory cap, read-only filesystem except `media/`). Logs: `journalctl -u mahitaji -f`.

The maintenance timer runs hourly: `expire_unpaid_orders` (cancels M-Pesa orders unpaid after
`UNPAID_ORDER_EXPIRY_HOURS`, releasing their stock) and `clearsessions`. The backup timer runs
nightly at 02:30 (see §8).

## 7. Nginx + TLS

```bash
cp deploy/nginx/mahitaji-proxy.conf /etc/nginx/snippets/
cp deploy/nginx/mahitaji.conf /etc/nginx/sites-available/mahitaji
ln -s /etc/nginx/sites-available/mahitaji /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d mahitaji.co.ke -d www.mahitaji.co.ke     # writes the ssl_* lines
certbot renew --dry-run
```

What the Nginx config does: TLS 1.2/1.3 only; serves `/static/` (1-year cache) and `/media/`
(1-week cache, uploads can never execute) itself; caps request bodies at 1 MB except for the
admin's imports and photo uploads (200 MB); rate-limits sign-in/registration/password
reset (10/min), payment endpoints (20/min), the JSON API and assistant chat (60/min) and the
rest (30/s) per address; drops WordPress/phpMyAdmin/.env scanners; forwards the real client
address so Django's own sign-in limits work.

## 8. Backups

`deploy/scripts/backup.sh` dumps the database (`--single-transaction`, no locking), tars
`media/`, copies `.env`, keeps 14 days locally in `/srv/mahitaji/backups`, and syncs to an
off-site rclone remote when `BACKUP_REMOTE` is set in the service's environment
(`systemctl edit mahitaji-backup` → `[Service] Environment=BACKUP_REMOTE=b2:mahitaji-backups`
after `rclone config`). **Rehearse a restore before launch**:

```bash
zcat /srv/mahitaji/backups/db-<stamp>.sql.gz | mysql mahitaji_scratch   # into a scratch database
```

## 9. Releasing a change

```bash
sudo -u mahitaji /srv/mahitaji/app/deploy/scripts/deploy.sh
```
(pull → pip install → `check --deploy` → migrate → collectstatic → restart; it stops if the
check fails.) Allow the `mahitaji` user `sudo systemctl restart mahitaji` in sudoers for that.

## 10. Go-live checks

- `curl -I https://mahitaji.co.ke` shows `strict-transport-security`, `x-frame-options: DENY`, `x-content-type-options: nosniff`.
- Wrong password ×9 on `/login/` returns 429 (proves Redis is wired in; `redis-cli keys 'mahitaji*'` shows the counters).
- Place a cash-on-delivery order and an M-Pesa order of KSh 10 with real credentials; the M-Pesa order flips to Paid on its own.
- Download an order PDF; upload a product image in the admin and see it at `/media/products/...`.
- `/admin/` is a 404; the admin is at `/<ADMIN_URL>`.
- `systemctl list-timers` shows both timers; `journalctl -u mahitaji-maintenance` after the first hour.
- Reboot: `systemctl reboot` and confirm the site is back without touching anything.
- Set `SECURE_HSTS_SECONDS=31536000` after a few weeks of trouble-free HTTPS.

## What is handled in code (no server work needed)

- HTTPS-only cookies, HSTS, nosniff, referrer policy, clickjacking denial, `SECRET_KEY` required.
- Sign-in limits: 8 failures per account+address, 30 per address, 15-minute pause; registration 10/h and password-reset emails 5/h per address; API 60/min anonymous, 300/min signed in.
- Staff sessions end after 8 idle hours (`STAFF_SESSION_IDLE_HOURS`); customers keep 14-day sessions.
- M-Pesa callbacks use a secret URL; a callback without it never changes an order by itself (Safaricom is asked instead). Prompts are throttled per order (20 s) and per customer (6/h).
- One account may have 5 orders open at a time; unpaid M-Pesa orders expire after 24 h and unconfirmed cash orders after 72 h (`UNCONFIRMED_COD_ORDER_EXPIRY_HOURS`, 0 disables). Staff confirm a cash order by marking it Paid, Shipped or Delivered in the admin.
- Storefront pages carry a Content-Security-Policy (scripts only from this origin or nonce-tagged inline blocks).
- Chat logs store a hash of the visitor's session, never the session key itself.
- Product image URLs in CSV imports are only fetched from public addresses (never loopback, private or metadata ranges).
- Order confirmation emails are sent from a background thread with a 10-second SMTP timeout.
- Stock is reserved at checkout and released on cancellation or expiry.
