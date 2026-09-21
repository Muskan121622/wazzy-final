import sys
import os
import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection
from services.auth_service import get_current_user, assert_trip_ownership
from services.gis import haversine_distance, resolve_location_coordinates
from services.optimizer import add_place_to_itinerary

router = APIRouter(prefix="/api/trip", tags=["Trip"])


class PreferenceUpdate(BaseModel):
    quietness: float = 0.9
    seafood: float = 0.9
    budget_max: int = 1800
    crowd_tolerance: float = 0.2
    energy_level: str = "medium"


class AddActivityRequest(BaseModel):
    trip_id: str
    place_id: str
    day_number: int = 1
    time_slot: str | None = None


@router.get("")
def list_my_trips(user: dict = Depends(get_current_user)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY created_at DESC", (user["id"],))
    trips = [dict(t) for t in cursor.fetchall()]
    conn.close()
    return {"trips": trips}


@router.post("/add-activity")
def add_activity(req: AddActivityRequest, user: dict = Depends(get_current_user)):
    assert_trip_ownership(req.trip_id, user["id"])
    return add_place_to_itinerary(req.trip_id, req.place_id, req.day_number, req.time_slot)


@router.get("/{trip_id}")
def get_trip_details(trip_id: str, user: dict = Depends(get_current_user)):
    assert_trip_ownership(trip_id, user["id"])

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    trip = dict(cursor.fetchone())

    # Fetch THIS trip's user preferences (never a random stranger's)
    cursor.execute("SELECT * FROM preferences WHERE user_id = ?", (trip["user_id"],))
    pref_row = cursor.fetchone()
    preferences = dict(pref_row) if pref_row else {}

    origin_coord = resolve_location_coordinates(trip["destination"] if trip.get("destination") else "Goa")

    # Fetch Itinerary Items joined with Places
    cursor.execute("""
    SELECT i.id as item_id, i.day_number, i.time_slot, i.time_period, i.status, i.version,
           p.id as place_id, p.name as place_name, p.area, p.category, p.indoor_flag,
           p.crowd_level, p.price, p.rating, p.opening_hours, p.description, p.plan_b_id, p.lat, p.lon,
           fb.name as fallback_name, fb.category as fallback_category
    FROM itinerary_items i
    JOIN places p ON i.place_id = p.id
    LEFT JOIN places fb ON i.fallback_place_id = fb.id
    WHERE i.trip_id = ?
    ORDER BY i.day_number ASC, CASE i.time_period WHEN 'Morning' THEN 1 WHEN 'Afternoon' THEN 2 WHEN 'Evening' THEN 3 ELSE 4 END
    """, (trip_id,))

    items_rows = cursor.fetchall()

    # Group by Day
    days = {}
    for r in items_rows:
        row_dict = dict(r)
        d_num = row_dict["day_number"]
        if d_num not in days:
            days[d_num] = []

        # Calculate distance explicitly for the UI
        dist_km = haversine_distance(origin_coord["lat"], origin_coord["lon"], row_dict["lat"] or 15.5, row_dict["lon"] or 73.7)

        # Calculate duration based on category
        cat_lower = (row_dict["category"] or "").lower()
        if "restaurant" in cat_lower or "food" in cat_lower or "cafe" in cat_lower:
            duration_hrs = 1.5
        elif "beach" in cat_lower:
            duration_hrs = 3.0
        elif "nature" in cat_lower or "farm" in cat_lower or "plantation" in cat_lower:
            duration_hrs = 2.5
        elif "shopping" in cat_lower or "market" in cat_lower:
            duration_hrs = 2.0
        else:
            duration_hrs = 1.5  # Default for indoor/culture/forts

        days[d_num].append({
            "item_id": row_dict["item_id"],
            "time_slot": row_dict["time_slot"],
            "time_period": row_dict["time_period"],
            "status": row_dict["status"],
            "version": row_dict["version"],
            "place": {
                "id": row_dict["place_id"],
                "name": row_dict["place_name"],
                "area": row_dict["area"],
                "category": row_dict["category"],
                "indoor_flag": bool(row_dict["indoor_flag"]),
                "crowd_level": row_dict["crowd_level"],
                "price": row_dict["price"],
                "rating": row_dict["rating"],
                "opening_hours": row_dict["opening_hours"],
                "description": row_dict["description"],
                "distance_km": round(dist_km, 1),
                "duration_hrs": duration_hrs
            },
            "fallback": {
                "name": row_dict["fallback_name"],
                "category": row_dict["fallback_category"]
            } if row_dict["fallback_name"] else None
        })

    # Fetch Version Log
    cursor.execute("SELECT id, trip_id, version_number, change_description, timestamp FROM trip_versions WHERE trip_id = ? ORDER BY version_number DESC", (trip_id,))
    versions = [dict(v) for v in cursor.fetchall()]

    # Fetch Audit Actions
    cursor.execute("SELECT * FROM agent_actions WHERE trip_id = ? ORDER BY timestamp DESC LIMIT 5", (trip_id,))
    actions = [dict(a) for a in cursor.fetchall()]

    # Fetch live PENDING recovery proposals (proactive alerts surface here too)
    cursor.execute("""
    SELECT rp.id, rp.type, rp.reason, rp.score, rp.status, rp.proposed_time_slot,
           i.day_number, i.time_slot as current_slot,
           orig.name as current_place, prop.name as proposed_place
    FROM recovery_proposals rp
    JOIN itinerary_items i ON rp.original_item_id = i.id
    LEFT JOIN places orig ON i.place_id = orig.id
    LEFT JOIN places prop ON rp.proposed_place_id = prop.id
    WHERE rp.trip_id = ? AND rp.status = 'PENDING'
    ORDER BY rp.created_at DESC
    """, (trip_id,))
    pending_proposals = [dict(p) for p in cursor.fetchall()]

    conn.close()

    return {
        "trip": trip,
        "preferences": preferences,
        "itinerary_days": days,
        "versions": versions,
        "audit_actions": actions,
        "pending_proposals": pending_proposals
    }


@router.post("/preferences")
def update_preferences(pref: PreferenceUpdate, user: dict = Depends(get_current_user)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO preferences (user_id, quietness, seafood, budget_max, crowd_tolerance, energy_level)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        quietness = excluded.quietness,
        seafood = excluded.seafood,
        budget_max = excluded.budget_max,
        crowd_tolerance = excluded.crowd_tolerance,
        energy_level = excluded.energy_level
    """, (user["id"], pref.quietness, pref.seafood, pref.budget_max, pref.crowd_tolerance, pref.energy_level))

    conn.commit()
    conn.close()

    return {"status": "SUCCESS", "message": "Trip preferences updated and synced."}


class TripGenerateRequest(BaseModel):
    destination: str = "Baga, Goa"
    days_count: int = 4
    quietness: float = 0.9
    seafood: float = 0.9
    total_budget: int = 15000
    crowd_tolerance: float = 0.2
    energy_level: str = "medium"
    start_date: str = "2026-09-20"
    end_date: str = "2026-09-24"
    dest_lat: float | None = None
    dest_lon: float | None = None


@router.post("/generate")
def generate_trip(req: TripGenerateRequest, user: dict = Depends(get_current_user)):
    from services.optimizer import generate_custom_trip
    res = generate_custom_trip(
        user=user,
        destination=req.destination,
        days_count=req.days_count,
        quietness=req.quietness,
        seafood=req.seafood,
        total_budget=req.total_budget,
        crowd_tolerance=req.crowd_tolerance,
        energy_level=req.energy_level,
        start_date=req.start_date,
        end_date=req.end_date,
        dest_lat=req.dest_lat,
        dest_lon=req.dest_lon,
    )
    return res
