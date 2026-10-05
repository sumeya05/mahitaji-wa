#!/usr/bin/env bash
# Release the current main branch: pull, install, migrate, collect static files, restart.
# Run as the mahitaji user:  sudo -u mahitaji /srv/mahitaji/app/deploy/scripts/deploy.sh
set -euo pipefail
APP=/srv/mahitaji/app
VENV=/srv/mahitaji/venv
cd "$APP"
git pull --ff-only
"$VENV/bin/pip" install -q -r requirements.txt
"$VENV/bin/python" manage.py check --deploy --fail-level ERROR
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput --clear
sudo systemctl restart mahitaji
sleep 2
systemctl is-active --quiet mahitaji && echo "mahitaji restarted" || { echo "mahitaji failed to start"; journalctl -u mahitaji -n 40 --no-pager; exit 1; }
