#!/usr/bin/env bash
# Nightly backup: a compressed MySQL dump plus the media folder, kept locally for 14 days and
# mirrored off the server when BACKUP_REMOTE is set (an rclone remote, e.g. "b2:mahitaji-backups").
# Credentials come from /srv/mahitaji/app/.env (DB_NAME, DB_USER, DB_PASSWORD).
set -euo pipefail
APP=/srv/mahitaji/app
DEST=/srv/mahitaji/backups
KEEP_DAYS=14
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
mkdir -p "$DEST"
chmod 700 "$DEST"
set -a; source "$APP/.env"; set +a
stamp=$(date +%Y-%m-%d_%H%M)
db="$DEST/db-$stamp.sql.gz"
# --single-transaction: a consistent snapshot without locking the shop.
MYSQL_PWD="$DB_PASSWORD" mysqldump --single-transaction --quick --routines --triggers \
    -h "${DB_HOST:-127.0.0.1}" -u "$DB_USER" "$DB_NAME" | gzip -6 > "$db"
tar -czf "$DEST/media-$stamp.tar.gz" -C "$APP" media
cp "$APP/.env" "$DEST/env-$stamp"    # the secrets are part of the recovery (SECRET_KEY, M-Pesa)
chmod 600 "$DEST"/*
find "$DEST" -type f -mtime +"$KEEP_DAYS" -delete
if [ -n "$BACKUP_REMOTE" ] && command -v rclone >/dev/null; then
    rclone sync "$DEST" "$BACKUP_REMOTE" --quiet
fi
echo "backup done: $db ($(du -h "$db" | cut -f1))"
