# SnapSphere

**Photographer Booking & Recommendation Platform** — Final Year Project

A mobile app where buyers discover, compare and book professional
photographers, guided by a recommendation engine, plus a classifieds shop
(OLX-style) where anyone can post camera and mobile gear for sale and buyers
message the seller to agree a deal.

| | |
|---|---|
| **Mobile** | React Native (Expo SDK 58) + TypeScript |
| **Backend** | Django 5 + Django REST Framework + Channels (ASGI) |
| **Database** | MySQL 8 |
| **Cache / queue / realtime** | Redis 7 (3 logical DBs) |
| **Background jobs** | Celery + Celery Beat |
| **ML** | scikit-learn, pandas, scipy |
| **Auth** | JWT (rotating refresh tokens + blacklist + version kill switch) |
| **Currency** | PKR |

---

## Repository layout

```
hassan/
├── backend/          Django REST API  (15 apps, 57 domain models)
├── mobile/           React Native app (Expo, TypeScript)
├── ml/               Datasets, feature pipelines, model training
│   ├── data/raw/     The 11 source CSVs
│   ├── pipelines/    ingest · features · scorer · trainers (ranker, CF, content, sentiment)
│   └── artifacts/    Trained models (.joblib) + metrics.json
├── docs/             Architecture + project-state documents
└── prototype/        The original SnapSphere RN prototype (UI reference)
```

---

## Running it

See **[HOW-TO-RUN.md](HOW-TO-RUN.md)** for a fresh clone. Once installed and
seeded, three scripts do the work:

```bash
./start.sh              # MySQL + Redis + Django API
./start.sh --workers    # ...plus Celery worker and scheduler (scheduled jobs)
./test.sh               # end-to-end API smoke test
./stop.sh               # stop the servers
```

`start.sh` is idempotent — it checks what is already running rather than
starting duplicates, and tells you if the database is unseeded.

Then open:

| | |
|---|---|
| Swagger UI | http://127.0.0.1:8000/api/v1/docs/ |
| Django admin | http://127.0.0.1:8000/django-admin/ |
| Health check | http://127.0.0.1:8000/health/ |

### Mobile app

```bash
cd mobile && npx expo start
```

Scan the QR code with **Expo Go** (the SDK 58 build). The app auto-detects
your machine's LAN IP from the Expo host, so no configuration is normally
needed. To override, set `EXPO_PUBLIC_API_URL` in `mobile/.env` — see
`src/api/config.ts`.

Your phone and computer must be on the same Wi-Fi.

### Machine learning

```bash
backend/.venv/bin/python -m ml.pipelines.ingest --audit   # data quality report
backend/.venv/bin/python -m ml.train                      # train all models
backend/.venv/bin/python -m ml.train --only sentiment     # just one
```

(On Windows the interpreter is `backend/.venv/Scripts/python.exe`.)

---

## What the app does

| Role | Main features |
|---|---|
| **Buyer** | Home with AI recommendations and "Near me", search with 12 filters and 6 sorts, AI matchmaker (typed request) and visual search (reference photo), photographer profiles, hour-based booking and 1/2-day packages, chat, reviews, saved items, Shop (buy and sell gear) |
| **Photographer** | Dashboard (earnings, funnel, top services), booking requests and jobs, services and packages, calendar, portfolio, review replies, Shop |
| **Admin** | Signs in on the normal login screen. Tabs: **Dashboard**, **Users** (search, block/unblock), **Reports** (reported ads, reviews and chat messages — take down or dismiss), **Bookings** (search, view, force-cancel), **More** (audit log, platform settings, broadcasts) |

Every admin action is re-checked on the server (ADMIN role only) and written
to an audit log that cannot be edited.

---

## Seeded accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@snapsphere.pk` | `admin12345` |
| Photographer | `photographer1@snapsphere.pk` … `photographer200@…` | `photographer123` |
| Buyer | `buyer1@snapsphere.pk` … | `buyer12345` |

The seed builds on the supplied datasets: **~200 photographers, ~245 buyers,
1,000 services, ~52,000 bookings, ~51,800 reviews, 126 shop ads, 684
portfolio images.** The booking and review history is **generated** so that
each photographer's headline rating has real rows behind it; review text is
drawn from `yelp.csv` and matched to the star rating.

---

## Data-quality findings

Two of the supplied datasets contain **randomly assigned labels**. This was
verified statistically, not assumed, and it shaped the entire ML design.
Run `python -m ml.pipelines.ingest --audit` to reproduce.

### `reviews_feedback.csv` — sentiment labels are noise

300 rows contain only **5 distinct review sentences**, and every sentence
carries all three labels:

```
"Amazing service and very professional."  → Positive 24, Neutral 24, Negative 15
"Not satisfied with the booking process." → Positive 21, Neutral 18, Negative 17
```

**Response:** the sentiment model is trained on `yelp.csv` (44,610 real
reviews with trustworthy star ratings) instead. It reaches **78.9% accuracy /
0.68 macro-F1** on held-out data.

### `buyer_interactions.csv` — booking outcomes are random

Not one photographer attribute predicts whether a booking happened:

| Feature | Pearson r | p |
|---|---|---|
| avg_rating | −0.006 | 0.90 |
| reviews_count | 0.054 | 0.23 |
| response_time | −0.000 | 0.998 |
| χ²(category, booking_status) | — | 0.95 |

Booking rate by rating quartile: **32.3% / 32.5% / 32.8% / 31.2%** — flat.

**Response:** the ranker is no longer trained on this file. The first version
shipped a transparent weighted scorer (a regressor fitted on this CSV scored
R² = −0.03, worse than predicting the mean). The current ranker
(`ml/pipelines/train_ranker.py`) is trained on the **booking history in the
database** instead — see below.

---

## Model results (held-out)

| Model | Algorithm | Result |
|---|---|---|
| **Sentiment** | TF-IDF (1,2-gram) + LogisticRegression | accuracy **0.789**, macro-F1 **0.681** |
| **Ranker** | RandomForest, chosen over Ridge and GradientBoosting by grouped cross-validation | temporal hold-out: R² **0.924**, Spearman **0.96** |
| **Collaborative filter** | Item-item cosine on weighted implicit feedback | HitRate@10 **0.094** (1.75× random) at 1.1% density |
| **Content model** | TF-IDF photographer profiles vs the buyer's taste | HitRate@10 **0.046** (popularity baseline 0.093) |

**Reading these honestly:**

* **Ranker.** It predicts how much a photographer will be booked in the next
  180 days from what was known before. It is evaluated on later time periods
  it never saw. Its training data is the **seeded** booking history, which
  gives each photographer a steady booking rate — so past popularity
  (`popularity_score`, 95% of feature importance) predicts the future almost
  perfectly. The score shows the pipeline works end to end; it is not
  evidence of how well it predicts real buyers. The nightly retrain
  (`apps/recommendations/tasks.py`) will learn from real bookings as they
  accumulate.
* **Collaborative filter.** An earlier evaluation reported 0.97 — it was
  leaking, because the similarity matrix included the held-out interaction.
  It now recomputes similarity per trial.
* **Content model.** It scores below popularity on this data. Its role in the
  hybrid blend is cold start: it can match a buyer's stated preferences
  before they have any history.

The matchmaker is a **rule-based parser** (city, budget, category, dates) and
visual search compares **hand-crafted image features** (colour, contrast,
texture) by cosine similarity — neither uses a language model or a neural
network.

---

## Notable engineering decisions

**MySQL silently drops conditional unique constraints.** Django's
`UniqueConstraint(condition=...)` becomes a partial index on PostgreSQL and
*nothing at all* on MySQL — with only a `models.W036` warning. The
double-booking guard, order idempotency and four other integrity rules were
therefore not in the database. Restored using MySQL's generated-column idiom
(`apps/*/migrations/000*_partial_unique_*.py`); verified by test:

```
Duplicate entry '280|2026-09-25|16:00:00' for key 'bookings.uniq_active_booking_slot'
```

**`token_version` is enforced on every request.** Stock
`JWTAuthentication` validates only signature and expiry, so blocking a user
left their access token working for up to 30 minutes.
`apps/accounts/authentication.py` re-checks the version claim and account
state on every call, at the cost of zero extra queries.

**Concurrent token refresh is single-flight.** Five parallel 401s would
otherwise trigger five refreshes, four of them reusing an already-rotated
token — which the backend's reuse detection treats as theft and responds to by
revoking the whole family. `mobile/src/api/client.ts` queues them onto one
promise.

**Layering is enforced by convention, not framework.**
`views → serializers → services/selectors → models`, one direction only.
Writes live in `services.py`, reads in `selectors.py`, and no app imports
another app's `models.py` except for foreign-key declarations.

---

## Known limitations

* **No payment gateway.** Booking commission and payout are calculated and
  shown, but no money moves. The shop is classifieds: buyer and seller settle
  off-platform.
* **Built but not shown in the app:** wallet and top-ups, photographer approval
  requests (new photographers are listed automatically), and shop orders and
  downloads (kept so orders placed before checkout was removed still work).
* **Notifications:** in-app notifications work; push delivery is a log line
  (no Expo/FCM credentials). Email uses Django's console backend in
  development, so verification codes appear in the server log.
* **Platform settings** (admin → More → Platform settings) are stored and
  audited, but the server currently reads its values from configuration
  (`config/settings/base.py`), not from these rows.
* **Rate limits** are configured but switched off in development
  (`config/settings/dev.py`).
* **Scheduled jobs** (booking expiry, auto-complete, reminders, nightly
  retrain, analytics rollups) run only when Celery is started:
  `./start.sh --workers`.
* **Chat** messages are stored on the server; they are not end-to-end
  encrypted.

---

## Documentation

| Document | Contents |
|---|---|
| **[HOW-TO-RUN.md](HOW-TO-RUN.md)** | Step-by-step setup from a fresh clone, Windows included |
| **[docs/PROJECT-STATE.md](docs/PROJECT-STATE.md)** | **Start here when resuming** — module status, decisions, traps already hit |
| [docs/01-system-architecture.md](docs/01-system-architecture.md) | ADRs, NFRs, security model, threat model, folder structure, deployment topology |

---

## Status

| # | Module | State |
|---|---|---|
| 1 | System architecture | ✅ Documented |
| 2 | Database design | ✅ 57 domain models, migrated, seeded |
| 3 | Authentication | ✅ Register, login, email verification (OTP), password reset |
| 4 | Buyer module | ✅ Profile, saved items, near me |
| 5 | Photographer module | ✅ Services and packages, calendar, profile editing, dashboard |
| 6 | Portfolio | ✅ Upload (EXIF stripped, 3 sizes), featured photos, viewer |
| 7 | Booking | ✅ Hour-based, 1/2-day packages, state machine, timeline |
| 8 | Shop | ✅ OLX-style classifieds: post, edit, mark sold, delete, report, message seller |
| 9 | Reviews & ratings | ✅ Write, edit, reply, helpful votes, report, sentiment |
| 10 | AI recommendation | ✅ Hybrid engine, matchmaker, visual search |
| 11 | Search & filters | ✅ 12 filters, 6 sorts, distance |
| 12 | Notifications | ✅ In-app bell, preferences, quiet hours (push delivery not connected) |
| 13 | Chat | ✅ Live chat, read receipts, delete for me / everyone, smart replies |
| 14 | Admin | ✅ Dashboard, users, reports, bookings, audit log, settings, broadcasts |
| 15 | Analytics | ✅ Photographer dashboard, nightly rollups |
| 16 | API documentation | ✅ Auto-generated at `/api/v1/docs/` |
| 17 | React Native screens | ✅ Buyer, photographer and admin apps |
| 18 | Deployment | ✅ Documented in `docs/01` §12 |

**Code (measured 24 Nov 2026):** 185 backend files (29,103 lines, excluding
migrations and tests) · 98 mobile files (24,771 lines) · 10 ML files (1,749
lines).
**Tests:** 726 backend tests (pytest) · `./test.sh` end-to-end smoke test.
**Data:** 78 tables · 448 users · 201 photographers · 52,203 bookings ·
51,822 reviews · 126 shop ads.
