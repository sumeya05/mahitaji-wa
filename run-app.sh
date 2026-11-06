#!/usr/bin/env bash
# Run the Mahitaji Fleet app in a browser, in a phone frame, against a local copy of the server.
#
#     ./run-app.sh
#
# Starts Django on the website's MySQL database (settings from .env), so everyone signs in with
# their own account, and the Expo web app in mahitaji-fleet/. Then opens
# http://localhost:8081/phone.html. Press Ctrl+C to stop both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_URL="http://localhost:8081/phone.html"
LOG="${TMPDIR:-/tmp}/mahitaji-fleet-server.log"
export DEBUG=true USE_SQLITE=false

for port in 8000 8081; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "Port $port is already in use. Is the app already running? Stop it with: kill \$(lsof -ti tcp:$port)"
    exit 1
  fi
done

echo "Starting Mahitaji Fleet. Keep this window open: the app runs only while it does."
echo "It opens in your browser in about 30 seconds. (A red 'libnspr4.so' line below is harmless.)"

cd "$ROOT"
if [ ! -x venv/bin/python ]; then
  echo "First run: setting up Python packages (a minute or two)…"
  python3 -m venv venv
  venv/bin/pip install -q -r requirements.txt
fi
# Bring the database up to date.
venv/bin/python manage.py migrate -v0
if [ ! -d mahitaji-fleet/node_modules ]; then
  echo "First run: installing the app's packages…"
  (cd mahitaji-fleet && npm install --silent)
fi

venv/bin/python manage.py runserver 0.0.0.0:8000 >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT

# Open the phone view once the app is being served.
(
  for _ in $(seq 1 120); do
    if curl -sf -o /dev/null "$APP_URL"; then
      if grep -qi microsoft /proc/version 2>/dev/null && command -v explorer.exe >/dev/null; then
        explorer.exe "$APP_URL" >/dev/null 2>&1 || true
      elif command -v xdg-open >/dev/null; then
        xdg-open "$APP_URL" >/dev/null 2>&1 || true
      elif command -v open >/dev/null; then
        open "$APP_URL" >/dev/null 2>&1 || true
      fi
      echo
      echo "  Mahitaji Fleet: $APP_URL"
      echo "  Sign in with your own account, or tap Create account.   Stop: Ctrl+C"
      echo
      exit 0
    fi
    sleep 1
  done
) &

cd mahitaji-fleet
BROWSER=none EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start --web
