# Mahitaji Fleet

The Android and iOS logistics app for **Mahitaji Enterprises Ltd**, built with Expo (React Native) and
Expo Router. It works on the Mahitaji Fleet masters in the Django project in the parent folder, through
the token-authenticated API at `/api/v1/fleet/` (`fleet/api.py`). Every check the admin makes (a driver
must have the Driver role, one vehicle per driver, an area's route in the same company...) applies in the
app too, because the server runs the same model validation.

## What's in it

| Tab / screen | What staff can do |
|---|---|
| **Home** | Counts of vehicles, drivers, turnboys, customers, areas and routes; quick "add" actions |
| **Vehicles** | Search by vehicle number or crew, filter by type; vehicle page with company, capacity, driver and turnboy (tap to call) |
| **Crew** | All employees, filter Driver / Turnboy / Other staff; employee page with role, company, phone and the vehicle they are on |
| **Customers** | Search by name, code or phone; customer page with contact, address, area, route and GPS location (opens in Maps) |
| **Areas** | Areas and routes; an area lists its customers, a route lists its areas |
| **Add / Edit** | Forms for vehicles (map driver and turnboy), employees (set the role), customers (record GPS from the phone), areas and routes |
| **Account** | Who is signed in, what they may do, sign out |

Everything needs signing in with a Mahitaji staff account. Anyone can tap **Create account** in the app,
but the new account can do nothing until the office approves it in **Admin → Fleet → Access requests**
(tick it, choose **Approve** in the actions menu). Approving puts the person in the **Logistics** group:
view, add and edit on every master. Everyone approved works on the same Mahitaji fleet.

What a person sees follows the permissions given in the admin (**Admin → Users / Groups**): a tab appears
only with the *view* permission for that master, and Add / Edit only with *add* / *change*. Companies are
set up in the admin and are read-only here.

## Running it in development

1. Start Django so phones on your Wi-Fi can reach it (from the repository root):

   ```bash
   ALLOWED_HOSTS='localhost,127.0.0.1,<your computer's LAN IP>' python manage.py runserver 0.0.0.0:8000
   ```

2. Start Expo:

   ```bash
   cd mahitaji-fleet
   npm install
   npx expo start
   ```

3. Scan the QR code with **Expo Go** (Android) or the Camera app (iPhone).

In development the app automatically uses port 8000 on the computer running Expo. To point it at
another server (staging, production, an ngrok tunnel), copy `.env.example` to `.env` and set
`EXPO_PUBLIC_API_URL`.

## Preview in a browser (phone frame)

From the repository root:

```bash
./run-app.sh
```

It sets things up on the first run, brings the local database up to date, adds sample fleet data if
there is none, starts the server and the app, and opens the phone view. Sign in as
**fleet@example.com / Fleet2026!secure**. `Ctrl+C` stops it.

To do the same by hand, use two terminals. Terminal 1, the server (from the repository root):

```bash
source venv/bin/activate
export DEBUG=true USE_SQLITE=true
python manage.py migrate
python manage.py seed_fleet_demo     # sample fleet + the fleet@example.com account; does nothing if fleet data exists
python manage.py runserver 0.0.0.0:8000
```

Terminal 2, the app:

```bash
cd mahitaji-fleet
EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start --web
```

Then open http://localhost:8081/phone.html. In a browser, "Use my current location" asks the browser for
your location instead of the phone's GPS.

## Checks

```bash
npm run typecheck   # TypeScript
npm run lint        # ESLint (expo lint)
npx expo-doctor     # dependency and config health
```

## Building for the stores

Builds are made in the cloud with EAS:

```bash
npx eas-cli@latest build --platform android   # .aab for Google Play
npx eas-cli@latest build --platform ios       # needs an Apple Developer account
```

Set `EXPO_PUBLIC_API_URL=https://<your production domain>` for production builds (in `eas.json` or the
EAS environment). The app identifiers are `ke.co.mahitaji.fleet` on both platforms (`app.json`).

## Code map

```
src/app/              screens (Expo Router: every file is a route)
  sign-in.tsx         the only screen before signing in
  (tabs)/             Home, Vehicles, Crew, Customers, Areas (tabs hidden without permission)
  vehicles/, employees/, customers/, areas/, routes/
    [id].tsx          a record's page
    edit.tsx          its add / edit form (edit when ?id= is given)
  account.tsx         signed-in account and sign out
src/components/       shared UI: ui.tsx (buttons, fields, cards), fleet.tsx (lists, pickers, detail rows),
                      record.tsx (record pages and forms)
src/lib/              API client and types, picker options, form helper, theme tokens, formatting
src/state/auth.tsx    sign-in (token in the phone's secure storage) and permissions
```
