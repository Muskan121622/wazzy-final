# Wayzyy TripOS
>**live Link - https://wazzy-final.vercel.app/**

> **Others generate your itinerary. Wayzyy keeps it alive.**
> 

Wayzyy TripOS is an adaptive, AI-powered travel operating system for post-booking trip
management. It generates a living day-by-day itinerary for a Goa trip and then **proactively**
monitors real-world conditions — live weather, your GPS position and travel time, and place
opening hours — to detect conflicts and propose (or auto-apply) recoveries before your plans
break.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Data model](#data-model)
- [The engines](#the-engines)
- [API reference](#api-reference)
- [Getting started (local)](#getting-started-local)
- [Configuration (environment variables)](#configuration-environment-variables)
- [Deployment](#deployment)
- [Security notes](#security-notes)

---

## What it does

- **Generates a custom itinerary** from your preferences (quietness, seafood, budget, energy
  level) ranked by a proximity-first scoring algorithm over a large Goa place catalogue.
- **Proactive recovery** — a background watcher scans active trips every ~20 minutes and raises
  *recovery proposals* when live weather turns rainy or a scheduled place will be closed.
- **GPS + time-aware delay engine** — computes your real arrival time from your live location and
  flags when you'd arrive late or after a venue closes, then proposes a swap or a time shift.
- **"What to do right now"** — context-aware top-3 recommendations you can add to any day with one tap.
- **Conversational agent** — a tool-calling LLM (Groq) that can search places, edit the itinerary,
  regenerate for budget, and answer with grounded, retrieved facts (RAG) instead of hallucinating.
- **Safe, audited mutations** — every automated change is versioned with optimistic concurrency,
  logged to an audit trail, and (for recoveries) only applied after an atomic, conflict-checked approve.

---

## Architecture

```
Frontend (Vercel · Next.js)
   │  axios + Bearer JWT ·  NEXT_PUBLIC_API_URL → backend /api
   ▼
Routers   (backend/routers/)     HTTP surface · auth guard · trip-ownership check
   ▼
Services  (backend/services/)    scoring · proactive engines · agent · RAG · weather · GIS
   ▼
Data layer (backend/database/db.py)   one dual-engine API → Neon Postgres (prod) | SQLite (dev)
```

- **Routers** never contain business logic — they validate input, enforce authentication, verify
  that the trip belongs to the caller, and delegate to services.
- **Services** do the work and talk to the database only through `get_connection()`.
- **Dual-engine data layer**: if `DATABASE_URL` starts with `postgres`, psycopg2 is used; otherwise
  it falls back to a local SQLite file. Both expose the same `?`-placeholder, dict-row API, so app
  code is identical across dev and prod.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Database | Neon serverless Postgres (prod) · SQLite (dev) |
| Auth | Self-contained HS256 JWT (stdlib), PBKDF2 password hashing |
| Scheduler | APScheduler (background proactive watcher) |
| LLM / Agent | Groq native tool-calling (`openai/gpt-oss-120b`) |
| Retrieval | Pure-Python TF-IDF + cosine "Goa Brain" (RAG) |
| Live data | Open-Meteo (weather), OpenStreetMap Nominatim (geocoding) |
| Geo data | OSM PBF ingestion (`goa.pbf`) via pyosmium |
| Frontend | Next.js (App Router), React, TypeScript, Tailwind |
| Hosting | Vercel (frontend) · Render (backend) · Neon (DB) |

---

## Repository layout

```
hiver/
├── backend/
│   ├── main.py                # FastAPI app, CORS, lifespan (init_db + background bootstrap)
│   ├── requirements.txt
│   ├── .env                   # local secrets (git-ignored)
│   ├── routers/               # auth · trip · chat · incident  (HTTP surface)
│   ├── services/              # optimizer · monitor · watcher · agent · goa_brain ·
│   │                          # weather_service · gis · host_service · rag_service · auth_service
│   ├── database/              # db.py (dual-engine + schema) · seed.py
│   ├── data/                  # goa_knowledge.json · goa_places.json · ingest_datasets.py
│   └── goa.pbf                # OpenStreetMap extract ingested into `places`
└── frontend/
    ├── src/app/               # landing page + /concierge dashboard
    ├── src/lib/api.ts         # axios client, session bootstrap, typed API calls
    └── ...
```

---

## Data model

Nine tables (created idempotently on startup in [`database/db.py`](backend/database/db.py)):

| Table | Stores |
|---|---|
| `users` | accounts (`id, name, email, password_hash, is_guest`) |
| `trips` | one row per trip (`user_id, destination, start/end_date, health_score, current_version, status`) |
| `preferences` | one scoring-input row per user (`quietness, seafood, budget_max, crowd_tolerance, energy_level`) |
| `places` | the full Goa catalogue — seeded + dataset + **OSM** rows (`category, indoor_flag, crowd_level, price, rating, opening_hours, lat, lon, source, plan_b_id`) |
| `itinerary_items` | the living itinerary, one activity per row (`trip_id, day_number, time_slot, time_period, place_id, status, version`) |
| `recovery_proposals` | proactive "swap this?" suggestions awaiting a decision (`type, reason, score, status, expires_at`) |
| `agent_actions` | audit trail of every automated change (`action, reason, tool_used, status`) |
| `incidents` | log of every condition check that fired (`type, detail, severity`) |
| `trip_versions` | immutable snapshot per version bump (`version_number, change_description, snapshot_json`) |

`itinerary_items.status` values: `SCHEDULED`, `ADDED_BY_AGENT`, `MODIFIED_BY_AGENT`, `CANCELLED`,
and `RECOVERED` (set when a recovery proposal is approved).

---

## The engines

### Scoring & generation — `services/optimizer.py`
`generate_custom_trip` resolves the stay coordinates, splits the budget across days, upserts
preferences, scores every place, dedupes by name, clusters geographically, and lays items into each
day (slot count driven by `energy_level`). The score is a weighted blend:

```
0.35·proximity + 0.25·preference + 0.20·weather + 0.10·budget + 0.10·rating + 0.05·seafood
```

`get_right_now_recommendation` returns the top-3 candidates for "what to do now";
`add_place_to_itinerary` backs the **Add to Day N** button (auto-picks the next free slot).

### Proactive recovery — `services/monitor.py`
Three detectors share proposal mechanics (dedupe, expiry, open-alternative search, incident log):

1. **Weather** — only fires when live Open-Meteo reports rain; proposes rain-safe indoor swaps.
2. **Delay / traffic** — real arrival math from the traveller's GPS + clock; proposes a swap or a time shift.
3. **Closed places** — flags items scheduled outside a venue's parsed `opening_hours`.

Approval (`approve_recovery_proposal`) is **concurrency-safe**: it re-checks PENDING/expiry/version,
then applies an atomic compare-and-swap version bump so two simultaneous approvals can't both win,
marks the item `RECOVERED`, recomputes `health_score`, and stores a `trip_versions` snapshot.

### Background watcher — `services/watcher.py`
APScheduler sweeps every in-progress trip (today's `day_number` derived from its dates) on an
interval and runs the weather + closed-place checks — this is what makes the system *proactive*.

### Live signals — `services/weather_service.py`, `services/gis.py`
Open-Meteo for real-time weather; a static Goa coordinate table plus live Nominatim geocoding,
with Haversine powering every proximity and travel-time calculation.

### Retrieval — `services/goa_brain.py`, `services/rag_service.py`
A pure-Python TF-IDF index over all places + the knowledge file, persisted to disk and reused,
providing token-budgeted, grounded context to the agent.

### Agent — `services/agent.py`
Groq tool-calling with tools: `get_weather`, `search_places_within_radius`, `update_itinerary`,
`remove_itinerary`, `regenerate_trip_budget`, `ask_host_tip`. Falls back to a friendly canned reply
if the LLM is unavailable.

---

## API reference

Base URL: `https://<backend-host>/api` · Authenticated routes require `Authorization: Bearer <token>`.

**Public**

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + DB engine |
| GET | `/` | status banner |
| POST | `/api/auth/register` | create account, returns JWT |
| POST | `/api/auth/login` | login, returns JWT |
| POST | `/api/auth/guest` | anonymous session, returns JWT |

**Authenticated**

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/auth/me` | current user |
| GET | `/api/trip` | list my trips |
| POST | `/api/trip/generate` | generate a living itinerary |
| GET | `/api/trip/{trip_id}` | full dashboard payload (days, versions, audit, pending proposals) |
| POST | `/api/trip/preferences` | update scoring preferences |
| POST | `/api/trip/add-activity` | add a recommended place to a day |
| POST | `/api/incident/trigger` | run live-weather recovery check |
| POST | `/api/incident/check-closed` | run closing-hours conflict check |
| POST | `/api/incident/evaluate-delay` | run GPS/time delay check |
| GET | `/api/incident/proposals` | list pending recovery proposals |
| POST | `/api/incident/approve` | apply a proposal (atomic version bump) |
| POST | `/api/incident/reject` | dismiss a proposal |
| GET | `/api/incident/right-now` | top-3 "what to do right now" |
| GET | `/api/incident/host-tips` | curated Superhost recommendations |
| POST | `/api/chat` | conversational tool-calling agent |

Interactive docs are available at **`/docs`** (Swagger UI) and **`/openapi.json`** on any running backend.

---

## Getting started (local)

### Prerequisites
- Python 3.11+ (3.14 works)
- Node.js 20+ / npm
- (Optional) a Neon Postgres URL — otherwise the backend uses a local SQLite file automatically

### Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
# create backend/.env (see Configuration below)
python -m uvicorn main:app --reload --port 8000
```

The API is now at `http://localhost:8000` (docs at `/docs`).

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000/api npm run dev
```

Open `http://localhost:3000`. The client bootstraps a guest session automatically, so you can
generate a trip without creating an account.

### Optional: seed / ingest data

```bash
cd backend
python database/seed.py            # demo user + places
python data/ingest_datasets.py     # dataset + OSM (goa.pbf) places
```

---

## Configuration (environment variables)

Create `backend/.env` (it is git-ignored — never commit real secrets):

```ini
# Database — leave empty to use local SQLite; set to a Postgres/Neon URL in prod
DATABASE_URL=postgresql://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/dbname?sslmode=require&channel_binding=require

# Signing key for JWTs — use a long random string
SECRET_KEY=change-me-to-a-long-random-secret

# Groq (agent tool-calling)
GROQ_API_KEY=gsk_your_groq_key_here

# Comma-separated list of allowed browser origins (no trailing slash)
ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.vercel.app

# How often the proactive watcher sweeps trips (minutes)
MONITOR_INTERVAL_MIN=20
```

Frontend:

```ini
NEXT_PUBLIC_API_URL=https://your-backend.onrender.com/api
```

---

## Deployment

| Piece | Host | Notes |
|---|---|---|
| Frontend | **Vercel** | Root Directory = `frontend`, Framework Preset = **Next.js**, set `NEXT_PUBLIC_API_URL` |
| Backend | **Render** | Root Directory = `backend`, start command `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Database | **Neon** | serverless Postgres; paste the real pooler URL into Render's `DATABASE_URL` |

**Two gotchas that bite most first deploys:**

1. **CORS** — `ALLOWED_ORIGINS` on the backend must include the exact frontend origin
   (e.g. `https://your-app.vercel.app`), or the browser blocks every call with a preflight error.
2. **`/api` suffix** — `NEXT_PUBLIC_API_URL` must end in `/api` (routes are mounted under
   `/api/...`). Environment variables are baked in at build time, so **redeploy** after changing them.

---

## Security notes

- Passwords are hashed with PBKDF2-SHA256 (200k iterations, per-user salt).
- Tokens are signed HS256 JWTs; `SECRET_KEY` must be a strong, unique value in production.
- Every trip-scoped endpoint verifies the trip belongs to the authenticated user before returning
  or mutating anything.
- `.env`, databases, caches, and `__pycache__` are excluded via `.gitignore`; secrets are never committed.

---

## License

All rights reserved.
