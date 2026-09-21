import sys
import os
import threading
from contextlib import asynccontextmanager

# Load .env BEFORE importing modules that read env vars (SECRET_KEY, DATABASE_URL).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.append(os.path.dirname(__file__))

from routers import trip, chat, incident, auth
from database.db import init_db, IS_POSTGRES


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Schema (idempotent) — Postgres if DATABASE_URL set, else SQLite
    init_db()

    # 2+3. Warm the Goa Brain index and start the proactive watcher OFF the startup
    # thread so the API accepts requests immediately (first real request would
    # otherwise block on Neon wake + TF-IDF build + a live-weather sweep).
    def _bootstrap():
        try:
            from services.goa_brain import get_brain
            get_brain().build()
        except Exception as e:
            print(f"[startup] Goa Brain build skipped: {e}")
        try:
            from services.watcher import start_watcher
            start_watcher()
        except Exception as e:
            print(f"[startup] watcher start failed: {e}")

    threading.Thread(target=_bootstrap, daemon=True).start()

    yield

    from services.watcher import stop_watcher
    stop_watcher()


app = FastAPI(
    title="Wayzyy TripOS Backend API",
    description="Adaptive AI Travel Operating System API for post-booking trip management, constraint scoring, and proactive recovery.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — explicit origins (Bearer-token auth, not cookies). Configure via env.
_default_origins = [
    "http://localhost:3000",
    "https://hiver.vercel.app",
    "https://wazzy.onrender.com",
]
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", ",".join(_default_origins)).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(trip.router)
app.include_router(chat.router)
app.include_router(incident.router)


@app.get("/health")
def health():
    return {"status": "OK", "db": "postgres" if IS_POSTGRES else "sqlite"}


@app.get("/")
def root():
    return {
        "system": "Wayzyy TripOS API",
        "status": "ONLINE",
        "vision": "Others generate your itinerary. Wayzyy keeps it alive."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
