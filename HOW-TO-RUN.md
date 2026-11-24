# How to Run SnapSphere — Step by Step

Complete setup instructions for running the project from a fresh clone:
the **backend** (Django REST API + MySQL + Redis) and the **frontend**
(React Native mobile app on Expo).

Follow Part A first — the mobile app is useless without the API running.

| Component | Technology | Runs on |
|---|---|---|
| Backend | Django 5 + DRF + Channels | `http://127.0.0.1:8000` |
| Database | MySQL 8 | `127.0.0.1:3306` |
| Cache / queue / websockets | Redis 7 | `127.0.0.1:6379` |
| Frontend | React Native (Expo SDK 58) | Expo Go on a phone, or an emulator |

---

## 0. Prerequisites

Install these once. Versions matter — the project is pinned to them.

| Tool | Version | Check with |
|---|---|---|
| Python | **3.12** | `python3.12 --version` |
| MySQL | 8.x | `mysql --version` |
| Redis | 7.x | `redis-server --version` |
| Node.js | 20 LTS or newer | `node --version` |
| npm | 10+ | `npm --version` |
| Expo Go app | the **SDK 58** build | on your phone (App Store / Play Store) |

### macOS (Homebrew)

```bash
brew install python@3.12 mysql redis node
brew services start mysql
brew services start redis
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv mysql-server redis-server \
                 pkg-config default-libmysqlclient-dev build-essential
sudo systemctl start mysql redis-server
```

### Windows

Native Windows works. Install Python 3.12, MySQL 8 (the MySQL Installer),
Redis (a Windows build, e.g. as a service), Node.js and **Git for Windows**,
then run every command below in **Git Bash**. Two differences from the
commands shown:

* The venv keeps its executables in `.venv/Scripts/` instead of `.venv/bin/`
  — e.g. `.venv/Scripts/python.exe manage.py migrate`.
* Create the venv with `py -3.12 -m venv .venv`.

`start.sh`, `stop.sh` and `test.sh` detect Windows themselves. If MySQL is not
running, `start.sh` starts a local server on the project's `mysql-data/`
folder; otherwise start your MySQL and Redis Windows services first.

(WSL2 with the Ubuntu steps also works.)

> **Homebrew path note.** On an Intel Mac Homebrew lives in `/usr/local`; on an
> Apple Silicon Mac it lives in `/opt/homebrew`. Every `/usr/local/opt/...`
> path below becomes `/opt/homebrew/opt/...` on Apple Silicon. The helper
> scripts find MySQL and Redis by their ports, so they work on either.

---

## 1. Get the code

```bash
git clone https://github.com/HassanAwan5005/Final-Year-Project.git hassan
cd hassan
```

The `main` branch holds the latest code.

You should see:

```
hassan/
├── backend/     Django REST API
├── mobile/      React Native app (the frontend)
├── ml/          Datasets + model training pipelines
├── docs/        Design documents
├── start.sh     helper: start MySQL + Redis + Django
├── stop.sh      helper: stop the servers
└── test.sh      helper: end-to-end API smoke test
```

### What a clone does NOT include

These are gitignored on purpose, so a fresh clone has none of them. The steps
below create each one:

| Not in the repo | Why | Created by |
|---|---|---|
| The database (`mysql-data/`) | Local data, not code | Steps A3, A5, A6 (create, migrate, seed) |
| Uploaded images (`backend/media/`) | Portfolio and ad photos | Step A6 (`seed_portfolio`), or users uploading in the app |
| Secrets (`backend/.env`) | Passwords and keys | Step A4 |
| Python packages (`backend/.venv/`) | Installed per machine | Steps A1–A2 |
| Node packages (`mobile/node_modules/`) | Installed per machine | Step B1 |
| Trained ML models | Build products | Step C4 (optional) |

---

# Part A — Backend (Django API)

Everything in this part runs from the `backend/` folder.

## A1. Create the Python virtual environment

```bash
cd backend
python3.12 -m venv .venv
```

On macOS with Homebrew, if `python3.12` is not on your PATH:

```bash
/usr/local/opt/python@3.12/bin/python3.12 -m venv .venv
```

Everything below calls the venv's interpreter directly as `.venv/bin/python`,
so you never need to remember whether the venv is activated. If you prefer to
activate it:

```bash
source .venv/bin/activate      # macOS / Linux
```

## A2. Install the Python dependencies

`mysqlclient` compiles against the MySQL C client, so it needs to be told where
the headers are **before** pip runs. On macOS:

```bash
export MYSQLCLIENT_CFLAGS="-I/usr/local/opt/mysql/include/mysql"
export MYSQLCLIENT_LDFLAGS="-L/usr/local/opt/mysql/lib -lmysqlclient"
```

On Linux the `default-libmysqlclient-dev` package handles this — skip the
exports. Then:

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/dev.txt
```

`requirements/dev.txt` pulls in `base.txt` (Django, DRF, Celery, Channels,
scikit-learn, pandas) plus the test and linting tools. Installation takes a few
minutes — pandas, numpy and scikit-learn are large.

For a deployment install without the dev tooling, use `requirements/prod.txt`.

## A3. Create the database and its user

Run these as MySQL root. The credentials must match what goes in `.env` in the
next step; the defaults below are what `.env.example` already expects.

```bash
mysql -u root -e "CREATE DATABASE snapsphere CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -e "CREATE USER 'snapsphere'@'localhost' IDENTIFIED BY 'snapsphere';"
mysql -u root -e "GRANT ALL PRIVILEGES ON snapsphere.* TO 'snapsphere'@'localhost';"
mysql -u root -e "GRANT ALL PRIVILEGES ON test_snapsphere.* TO 'snapsphere'@'localhost';"
mysql -u root -e "FLUSH PRIVILEGES;"
```

If your root account has a password, add `-p` and type it when prompted.
The `test_snapsphere` grant is what lets `pytest` create its own throwaway
database (Step C3) — without it every test fails with "Access denied".

Verify the user works:

```bash
mysql -u snapsphere -psnapsphere snapsphere -e "SELECT 1;"
```

## A4. Configure the environment file

```bash
cp .env.example .env
```

Then open `backend/.env` and set a real `SECRET_KEY`. Generate one with:

```bash
.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The other defaults work as-is for local development:

| Setting | Default | Meaning |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | dev settings (DEBUG on, console email) |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | `snapsphere` | must match Step A3 |
| `REDIS_URL` | `redis://127.0.0.1:6379` | DB 0 = cache, 1 = Celery, 2 = websockets |
| `ACCESS_TOKEN_LIFETIME_MINUTES` | `30` | JWT access token life |
| `BOOKING_MIN_LEAD_HOURS` | `24` | earliest a booking may be made |
| `PLATFORM_COMMISSION_PERCENT` | `10` | marketplace commission |

### Sending real emails (verification and password-reset codes)

With `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` (the dev
default) **no email is sent** — every code is printed in the Django server's
terminal instead. To deliver codes to real inboxes, use a Gmail account with
2-Step Verification on and an **App Password** (Google Account → Security →
App passwords), then set in `backend/.env`:

```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-address@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-app-password
DEFAULT_FROM_EMAIL=SnapSphere <your-address@gmail.com>
```

Restart the API afterwards. A failed send is logged as
"Password reset email failed: …" in the server output.

`.env` is gitignored and must never be committed — only `.env.example` is
tracked.

## A5. Run the migrations

```bash
.venv/bin/python manage.py migrate
```

This builds all 46 domain tables. It includes hand-written migrations
(`apps/*/migrations/000*_partial_unique_*.py`) that recreate conditional unique
constraints using MySQL generated columns, because MySQL silently drops
Django's `UniqueConstraint(condition=...)`. Do not skip them — the
double-booking guard lives there.

It also applies the data fixes added later, so always run it after pulling new
code:

| Migration | What it does |
|---|---|
| `catalog.0004_refresh_base_price` | Sets each photographer's "from Rs X" price to their cheapest service |
| `marketplace.0008_product_is_sold` | Lets sellers mark an ad as sold |
| `marketplace.0009_no_listing_approval` | Ads need no admin approval any more — puts waiting ads live |

## A6. Seed the database

```bash
.venv/bin/python manage.py seed_data --flush
```

Loads the real CSV datasets from `ml/data/raw/` — 200 photographers, 244
buyers, 600 services, bookings, reviews, about 125 shop ads for camera and
mobile gear (all live — ads need no admin approval), and daily analytics rows.
Takes a few minutes.

Every photographer gets coordinates in their city, which is what the Home
screen's "Near me" uses.

Then give photographers portfolio images — the "Find Similar Style" photo
search has nothing to match against without them:

```bash
.venv/bin/python manage.py seed_portfolio                    # generated sample images
.venv/bin/python manage.py seed_portfolio --from D:/photos   # or your own photos
```

Faster variants when you just need something to click through:

```bash
.venv/bin/python manage.py seed_data --flush --skip-history      # skip ~50k historical bookings/reviews
.venv/bin/python manage.py seed_data --flush --skip-analytics    # skip the daily analytics rows
```

## A7. Start the API server

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

Bind to `0.0.0.0`, **not** the default `127.0.0.1` — otherwise your phone
cannot reach it over Wi-Fi in Part B.

Leave this terminal running. You should see:

```
Starting ASGI/Daphne development server at http://0.0.0.0:8000/
```

## A8. Verify the backend

Open these in a browser:

| URL | What it is |
|---|---|
| http://127.0.0.1:8000/health/ | health check — should report `"status": "healthy"` |
| http://127.0.0.1:8000/api/v1/docs/ | Swagger UI — every endpoint, try them live |
| http://127.0.0.1:8000/api/v1/schema/ | raw OpenAPI schema |
| http://127.0.0.1:8000/django-admin/ | Django admin (log in as the seeded admin below) |

Or from the terminal, in a **second** window:

```bash
curl http://127.0.0.1:8000/health/
```

### Seeded login accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@snapsphere.pk` | `admin12345` |
| Photographer | `photographer1@snapsphere.pk` … `photographer200@…` | `photographer123` |
| Buyer | `buyer1@snapsphere.pk` … `buyer244@…` | `buyer12345` |

## A9. (Optional) Background workers

Only needed for scheduled jobs — booking expiry, nightly analytics, the ML
retrain. The app runs fine without them. Each needs its own terminal, run from
`backend/`:

```bash
.venv/bin/celery -A config worker -l info      # terminal 2
.venv/bin/celery -A config beat -l info        # terminal 3
```

---

# Part B — Frontend (React Native mobile app)

The backend from Part A must be running before you start this.

## B1. Install the Node dependencies

From the project root:

```bash
cd mobile
npm install
```

This includes `expo-location`, which the Home screen's "Near me" uses. Its
permission message is set in `mobile/app.json`; Expo Go already contains the
module, so nothing else needs installing.

## B2. Understand which SDK version this is

The app is on **Expo SDK 58** (`expo@^58.0.0`, React Native 0.88,
React 19.3). Expo Go supports exactly one SDK at a time, so the Expo Go build
on your test device must be the SDK 58 client. Running against a different
Expo Go gives:

```
ERROR  Project is incompatible with this version of Expo Go
```

**Do not change the SDK (`npx expo install expo@<version>`) without first
confirming the test devices' Expo Go supports it.** See `mobile/AGENTS.md` for
the SDK-58 notes already handled in this codebase.

## B3. Point the app at your backend

In most cases **you do not need to do anything** — `mobile/src/api/config.ts`
resolves the API URL automatically:

1. `EXPO_PUBLIC_API_URL` from `mobile/.env`, if set — always wins.
2. Otherwise the host Expo served the bundle from (your machine's LAN IP)
   — correct on a real phone.
3. Otherwise a platform fallback: `10.0.2.2` on the Android emulator,
   `127.0.0.1` on the iOS simulator.

To override it explicitly, find your machine's LAN IP:

```bash
ipconfig getifaddr en0        # macOS Wi-Fi
hostname -I | awk '{print $1}'  # Linux
```

Then create `mobile/.env`:

```
EXPO_PUBLIC_API_URL=http://192.168.1.42:8000/api/v1
```

Restart the bundler after changing `.env` — Expo reads it at startup.

> `localhost` / `127.0.0.1` never works from a physical phone: on the phone
> those addresses mean the phone itself, not your computer.

## B4. Start the app

```bash
npx expo start
```

Then choose how to run it:

| Target | How |
|---|---|
| **Physical phone (recommended)** | Scan the QR code with **Expo Go**. Phone and computer must be on the **same Wi-Fi network**. |
| Android emulator | Press `a` in the Expo terminal |
| iOS simulator (macOS only) | Press `i` |
| Web preview | Press `w` (partial — the app targets mobile) |

Useful keys in the Expo terminal: `r` reload, `j` open the debugger,
`m` toggle the dev menu, `Ctrl+C` quit.

If your Wi-Fi blocks device-to-device traffic (common on university and public
networks), fall back to a tunnel:

```bash
npx expo start --tunnel
```

## B5. Log in

Use any seeded account from the table in Step A8 — e.g.
`buyer1@snapsphere.pk` / `buyer12345` — or register a new buyer through the
sign-up screen.

## B6. Try "Near me"

On a buyer's Home screen, tap **Find photographers near me** and allow
location. It lists the nearest photographers within 25 km, widening to 100 km
and then 300 km if nobody is that close.

All seeded photographers are in Pakistani cities. A phone or emulator located
elsewhere sees "No photographers within 300 km". Emulators often default to
California, so set a Pakistani location first:

* **Android emulator:** ⋮ (Extended controls) → Location → search "Lahore" →
  Set location.
* **iOS simulator:** Features → Location → Custom Location — e.g. latitude
  `31.5204`, longitude `74.3587` (Lahore).

---

# Part C — Shortcuts and verification

## C1. The helper scripts (after first-time setup is done)

Once Parts A and B have been completed once, use these from the project root
instead of repeating the steps:

```bash
./start.sh              # start MySQL + Redis + the Django API
./start.sh --workers    # ...plus the Celery worker and scheduler
./stop.sh               # stop Django, Celery and the Expo bundler
./stop.sh --all         # ...also stop MySQL and Redis
```

`start.sh` is idempotent — it checks what is already running instead of
starting duplicates, warns you if the database looks unseeded, and prints the
LAN URL to use from your phone. Its logs go to `.logs/`.

```bash
tail -f .logs/django.log
```

## C2. Run the end-to-end API test

With the server running:

```bash
./test.sh
```

Exercises the live API the way the app does (155 checks): registration, login,
the JWT kill switch, blocked accounts, the database-level double-booking guard,
the full booking lifecycle, the shop and profile, the photographer studio,
analytics, reviews, notifications, chat, administration, and the docs
endpoints. Every check prints PASS or FAIL and the script exits non-zero on any
failure, so it is CI-usable. It cleans up after itself and leaves the seeded
data as it found it.

## C3. Run the unit test suite

```bash
cd backend
.venv/bin/python -m pytest                  # all tests
.venv/bin/python -m pytest apps/bookings    # one app
.venv/bin/python -m pytest --create-db      # after adding a migration
.venv/bin/python -m pytest --cov            # with coverage
```

`pytest.ini` sets `--reuse-db`, which keeps the schema between runs — pass
`--create-db` whenever you have added or changed a migration.

## C4. (Optional) Machine learning pipelines

Trained model artifacts are gitignored, so rebuild them if you need the
recommendation engine's learned components. From the project root:

```bash
backend/.venv/bin/python -m ml.pipelines.ingest --audit   # data-quality report
backend/.venv/bin/python -m ml.train                      # train all models
backend/.venv/bin/python -m ml.train --only sentiment     # just one
```

The API still serves recommendations without them: if a model file is
missing, the engine falls back to popularity ranking instead of failing.

## C5. Typecheck the frontend

```bash
cd mobile
npx tsc --noEmit
npx expo install --check     # report package drift against SDK 58
```

## C6. Updating an existing copy

When new code has been pushed, an existing setup needs more than `git pull`:

```bash
git pull

cd backend
.venv/bin/python -m pip install -r requirements/dev.txt   # new Python packages, if any
.venv/bin/python manage.py migrate                        # new tables and data fixes

cd ../mobile
npm install                                               # new app packages (e.g. expo-location)
npx expo start -c                                         # restart Expo with a clean cache
```

Then restart the API (`./stop.sh && ./start.sh`), and run the unit tests with
`--create-db` once, because the migrations changed.

Pulling does **not** reseed: your existing data stays, and the migrations fix
it in place. Only run `seed_data --flush` if you want to start over — it wipes
the database.

---

# Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `pip install` fails building `mysqlclient` | The MySQL C headers were not found. Set `MYSQLCLIENT_CFLAGS` / `MYSQLCLIENT_LDFLAGS` (Step A2), or install `default-libmysqlclient-dev` on Linux. |
| `django.db.utils.OperationalError: (2002 ...)` | MySQL is not running. `brew services start mysql` / `sudo systemctl start mysql`. |
| `Access denied for user 'snapsphere'@'localhost'` | The DB user does not exist or the password differs from `.env`. Redo Step A3. |
| Health check reports the cache is down | Redis is not running. `brew services start redis` / `sudo systemctl start redis-server`. |
| `Error: That port is already in use.` | Something already holds :8000. `./stop.sh`, or `lsof -ti:8000 \| xargs kill`. |
| Seed says a table is missing | Migrations were not applied. Run Step A5 before Step A6. |
| `test.sh` fails at "seed data present" | The database is empty. Run Step A6. |
| App shows "Network request failed" | The API URL is wrong or Django is bound to `127.0.0.1`. Restart it on `0.0.0.0:8000` and check Step B3. |
| `Project is incompatible with this version of Expo Go` | Your Expo Go is not the SDK 58 build. Update Expo Go on the phone — do not change the project's SDK. |
| Expo QR scan hangs on "Downloading bundle" | Phone and computer are on different networks, or the Wi-Fi isolates clients. Use `npx expo start --tunnel`. |
| Metro serves stale code after editing `.env` | Restart the bundler: `npx expo start -c` to also clear the cache. |
| Password-reset / verification code never arrives | Email is on the console backend, so the code is printed in the Django terminal. To send real emails, see "Sending real emails" in Step A4. |
| Photo search says "No style matches found" | No portfolio images exist yet. Run `manage.py seed_portfolio` (Step A6). |
| `pytest` fails with `Access denied ... 'test_snapsphere'` | Grant the test database privilege from Step A3. |
| `.env` changes have no effect on Django | The dev server caches settings at startup. Stop and restart `runserver`. |
| `Unable to resolve module expo-location` | The app packages are out of date. Run `npm install` in `mobile/`, then `npx expo start -c`. |
| "Near me" says no photographers within 300 km | The phone or emulator is not in Pakistan. Set a Pakistani location (Step B6). |
| "Near me" asks to allow location access | Location permission was denied. Turn it on for Expo Go in the phone's settings. |
| Prices, sold ads or "Post ad" behave like before | Migrations were not run after pulling. Run `manage.py migrate` (Step C6). |
| Admin wants to take down an ad | Ads go live without approval. A reported ad appears in the admin's **Reports** tab, where "Remove ad" takes it out of the shop. |

---

# Quick reference

**Every day, once set up — two terminals:**

```bash
# Terminal 1 — backend
cd hassan && ./start.sh

# Terminal 2 — frontend
cd hassan/mobile && npx expo start
```

**Ports**

| Service | Port |
|---|---|
| Django API | 8000 |
| MySQL | 3306 |
| Redis | 6379 |
| Expo dev server | 8081 |

**Key paths**

| Path | Contents |
|---|---|
| `backend/.env` | environment config (gitignored — create from `.env.example`) |
| `backend/apps/` | the 15 Django apps |
| `backend/private_media/` | digital product files, never publicly served |
| `mobile/src/api/config.ts` | API base URL resolution + every endpoint |
| `ml/data/raw/` | the source CSVs the seeder reads |
| `.logs/` | server logs written by `start.sh` |
| `docs/PROJECT-STATE.md` | module status, decisions, what is next |
