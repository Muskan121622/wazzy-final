"""
TripOS Watcher — the PROACTIVE engine.

A background scheduler that, every N minutes, scans every currently-active trip,
computes today's day_number from its start_date, and runs the live weather +
closing-hours recovery checks. Proposals it creates surface to the user via
GET /api/incident/proposals (or the trip detail's pending_proposals).

This is what turns the system from 'reactive demo' into a genuinely proactive
TripOS. Degrades gracefully if APScheduler is not installed.
"""
import os
import sys
import threading
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection
from services.monitor import create_recovery_proposal, check_closed_places

CHECK_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MIN", "20"))

_scheduler = None


def _today_day_number(start_date_str, end_date_str):
    try:
        start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        today = datetime.utcnow().date()
        if today < start or today > end:
            return None
        return (today - start).days + 1
    except Exception:
        return None


def scan_active_trips():
    """One proactive sweep across all in-progress trips."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, start_date, end_date FROM trips WHERE status = 'ACTIVE'")
    trips = [dict(r) for r in cur.fetchall()]
    conn.close()

    results = []
    for t in trips:
        day_number = _today_day_number(t["start_date"], t["end_date"])
        if day_number is None:
            continue  # not currently traveling
        try:
            weather = create_recovery_proposal(trip_id=t["id"], day_number=day_number)
            closed = check_closed_places(trip_id=t["id"], day_number=day_number)
            results.append({
                "trip_id": t["id"],
                "day_number": day_number,
                "weather_created": weather.get("proposal_count", 0),
                "closed_created": closed.get("proposal_count", 0),
            })
        except Exception as e:
            print(f"[watcher] trip {t['id']} scan failed: {e}")
    if results:
        print(f"[watcher] proactive sweep done: {len(results)} active trip(s) checked -> {results}")
    return results


def start_watcher():
    global _scheduler
    if _scheduler:
        return _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        print("[watcher] APScheduler not installed — proactive background scan DISABLED. "
              "Run 'pip install apscheduler' or trigger checks manually via /api/incident/trigger.")
        return None
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(scan_active_trips, "interval", minutes=CHECK_INTERVAL_MINUTES, id="tripos_watcher")
    _scheduler.start()
    # First proactive sweep shortly after boot, OFF the startup thread so the API
    # is ready immediately (don't block async lifespan on Neon + weather I/O).
    def _initial_sweep():
        try:
            scan_active_trips()
        except Exception as e:
            print(f"[watcher] initial sweep failed: {e}")
    threading.Thread(target=_initial_sweep, daemon=True).start()
    print(f"[watcher] proactive TripOS watcher started (every {CHECK_INTERVAL_MINUTES} min).")
    return _scheduler


def stop_watcher():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
