import sys
import os
import uuid
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection
from services.gis import haversine_distance, resolve_location_coordinates

def calculate_place_score(place, preferences, origin_area="Baga", is_rainy=False, max_radius_km=30.0):
    """
    Normalized 5-Factor Scoring Algorithm with Proximity-First Weighting:
    Score = 0.35 * Proximity + 0.25 * Preference + 0.20 * Weather + 0.10 * Budget + 0.10 * Rating
    """
    origin_info = resolve_location_coordinates(origin_area)

    # 1. Hard Filter: Weather Safety
    indoor = bool(place['indoor_flag'])
    if is_rainy and not indoor:
        weather_score = 0.1 # Heavily penalized if outdoor during rain
    elif is_rainy and indoor:
        weather_score = 1.0
    else:
        weather_score = 0.9 if not indoor else 0.8

    # 2. Preference match (Quietness & Crowd)
    crowd = place['crowd_level'].upper()
    crowd_penalty = 0.0
    if preferences['quietness'] > 0.6:
        if crowd == 'HIGH':
            crowd_penalty = 0.4
        elif crowd == 'MEDIUM':
            crowd_penalty = 0.15
        else:
            crowd_penalty = 0.0 # Low crowd matches high quietness!

    pref_score = max(0.1, 1.0 - crowd_penalty)

    # Seafood bonus / penalty
    desc = place['description'].lower()
    name = place['name'].lower()
    seafood_bonus = 0.0
    is_seafood_place = ('seafood' in desc or 'fish' in desc or 'seafood' in name or 'balchão' in desc)
    if preferences['seafood'] > 0.6:
        if is_seafood_place:
            seafood_bonus = 0.25
    elif preferences['seafood'] < 0.3:
        if is_seafood_place:
            seafood_bonus = -0.15 # Penalize heavy seafood spots when user sets seafood priority low

    # 3. Budget match
    price = place['price']
    max_budget = preferences['budget_max']
    if price <= max_budget:
        budget_score = 1.0
    else:
        overshoot = price - max_budget
        budget_score = max(0.1, 1.0 - (overshoot / max_budget))

    # 4. Rating & Quality (Normalized 0 - 1)
    rating_score = (place['rating'] / 5.0)

    # 5. Proximity Scoring (0 - 1)
    place_lat = place.get('lat', 15.5553)
    place_lon = place.get('lon', 73.7517)

    distance_km = haversine_distance(origin_info["lat"], origin_info["lon"], place_lat, place_lon)
    proximity_score = max(0.0, 1.0 - (distance_km / max_radius_km))

    total_score = (
        0.35 * proximity_score +
        0.25 * pref_score +
        0.20 * weather_score +
        0.10 * budget_score +
        0.10 * rating_score +
        0.05 * seafood_bonus
    )

    return {
        "place": place,
        "score": round(total_score * 100, 1),
        "distance_km": round(distance_km, 2),
        "origin_name": origin_info["clean_name"]
    }

def get_right_now_recommendation(trip_id="trip_1", current_time="16:45", current_area=None, is_rainy=False, radius_km=30.0):
    """
    'What should I do right now?' Context & GIS Engine.
    Filters candidate places via hard filters, applies normalized 5-factor scoring, deduplicates places, and returns Top 3.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Dynamic Destination Lookup
    cursor.execute("SELECT destination FROM trips WHERE id = ?", (trip_id,))
    t_row = cursor.fetchone()
    dest_str = t_row['destination'] if t_row else "Goa Stay"

    if current_area:
        dest_str = current_area

    origin_info = resolve_location_coordinates(dest_str)

    cursor.execute("""
    SELECT p.* FROM preferences p
    JOIN trips t ON t.user_id = p.user_id
    WHERE t.id = ?
    """, (trip_id,))
    pref_row = cursor.fetchone()
    if not pref_row:
        conn.close()
        return []

    preferences = dict(pref_row)

    cursor.execute("SELECT * FROM places")
    places = [dict(r) for r in cursor.fetchall()]
    conn.close()

    scored = []
    seen_names = set()

    for place in places:
        # Deduplicate strictly by normalized place name
        p_name = place['name'].strip().lower()
        if p_name in seen_names:
            continue
        seen_names.add(p_name)

        res = calculate_place_score(place, preferences, origin_area=dest_str, is_rainy=is_rainy, max_radius_km=radius_km)
        dist_km = res["distance_km"]
        score = res["score"]

        reasons = [
            f"📍 {dist_km} km from your {origin_info['clean_name']} stay (GIS OpenStreetMap)"
        ]
        if is_rainy and place['indoor_flag']:
            reasons.append("🌧️ 100% Indoor & Rain-safe")
        if preferences['quietness'] > 0.6 and place['crowd_level'] == 'Low':
            reasons.append("🤫 Low crowd - matches your quiet preference")
        if place['price'] <= preferences['budget_max']:
            reasons.append(f"💰 Under ₹{preferences['budget_max']} budget limit (₹{place['price']})")

        scored.append({
            "place": place,
            "score": score,
            "distance_km": dist_km,
            "match_percentage": int(min(99, score)),
            "reasons": reasons[:3],
            "dataset_source": place.get("source", "HuggingFace/Kaggle Candidate")
        })

    # Sort strictly by distance and score
    scored.sort(key=lambda x: (x['distance_km'], -x['score']))
    return scored[:3]


# Standard slots used to auto-place a newly added activity on a day.
_DAY_SLOT_TEMPLATE = ["09:30 AM", "01:00 PM", "04:30 PM", "07:30 PM"]


def _derive_time_period(time_slot):
    """Map a 'HH:MM AM/PM' slot to Morning/Afternoon/Evening/Night for sorting."""
    try:
        s = str(time_slot).strip().upper()
        half = "PM" if "PM" in s else "AM"
        hh = int(s.split(":")[0])
        hour = hh if half == "AM" else (12 if hh == 12 else hh + 12)
    except Exception:
        return "Afternoon"
    if hour < 12:
        return "Morning"
    if hour < 17:
        return "Afternoon"
    if hour < 21:
        return "Evening"
    return "Night"


def add_place_to_itinerary(trip_id, place_id, day_number, time_slot=None):
    """
    Add a recommended place as a NEW activity on a specific trip day.
    Used by the 'What to Do Right Now' Add button. When time_slot is omitted,
    the next free standard slot for that day is auto-selected. Never raises on
    normal validation misses — returns a structured error instead.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM trips WHERE id = ?", (trip_id,))
        if not cursor.fetchone():
            return {"status": "ERROR", "message": "Trip not found"}

        cursor.execute("SELECT id, name FROM places WHERE id = ?", (place_id,))
        p_row = cursor.fetchone()
        if not p_row:
            return {"status": "ERROR", "message": f"Place {place_id} not found"}
        place_name = p_row["name"]

        if not time_slot:
            cursor.execute(
                "SELECT time_slot FROM itinerary_items WHERE trip_id = ? AND day_number = ? AND status != 'CANCELLED'",
                (trip_id, day_number),
            )
            used = {r["time_slot"] for r in cursor.fetchall()}
            free = next((s for s in _DAY_SLOT_TEMPLATE if s not in used), None)
            time_slot = free or f"{(8 + len(used) * 3) % 24:02d}:00 PM"

        time_period = _derive_time_period(time_slot)
        item_id = f"item_{trip_id}_{day_number}_add_{uuid.uuid4().hex[:6]}"

        cursor.execute("""
        INSERT INTO itinerary_items (id, trip_id, day_number, time_slot, time_period, place_id, status, version)
        VALUES (?, ?, ?, ?, ?, ?, 'ADDED_BY_AGENT', 1)
        """, (item_id, trip_id, int(day_number), time_slot, time_period, place_id))

        action_id = f"action_{uuid.uuid4().hex[:12]}"
        cursor.execute("""
        INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
        VALUES (?, ?, 'ADD_ACTIVITY', ?, 'right_now_add', 'SUCCESS')
        """, (action_id, trip_id, f"Added {place_name} to Day {day_number} ({time_slot})"))

        conn.commit()
        return {"status": "SUCCESS", "item_id": item_id, "place_name": place_name,
                "day_number": int(day_number), "time_slot": time_slot, "time_period": time_period}
    finally:
        conn.close()

def generate_custom_trip(user, destination="Baga, Goa", days_count=4, quietness=0.9, seafood=0.9, total_budget=15000, crowd_tolerance=0.2, energy_level="medium", start_date="2026-09-20", end_date="2026-09-24", dest_lat=None, dest_lon=None, existing_trip_id=None):
    """
    Dynamically generates a custom living itinerary for ONE authenticated user.
    By default creates a NEW trip (uuid id) — never overwrites another user's trip.
    Pass existing_trip_id to rebuild a trip IN PLACE (used by budget-regenerate).
    Ranks available places from DB using Proximity-First Haversine GIS distances.
    Clusters daily activities geographically so travelers don't jump 50 km between morning & evening.
    """
    conn = get_connection()
    cursor = conn.cursor()

    user_id = user["id"]
    user_name = user.get("name") or "Traveler"
    rebuild = bool(existing_trip_id)
    trip_id = existing_trip_id if rebuild else "trip_" + uuid.uuid4().hex[:10]

    # Resolve dynamic origin coordinates
    if dest_lat is not None and dest_lon is not None:
        origin_coord = {"lat": dest_lat, "lon": dest_lon, "clean_name": destination.split(',')[0].strip()}
    else:
        origin_coord = resolve_location_coordinates(destination)

    # Calculate smart daily budget allocation
    daily_budget = round(total_budget / max(1, days_count), 2)
    max_activity_limit = round(daily_budget * 0.6, 2)

    # 1. Upsert Preferences for the authenticated user
    cursor.execute("""
    INSERT INTO preferences (user_id, quietness, seafood, budget_max, crowd_tolerance, energy_level)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        quietness = excluded.quietness,
        seafood = excluded.seafood,
        budget_max = excluded.budget_max,
        crowd_tolerance = excluded.crowd_tolerance,
        energy_level = excluded.energy_level
    """, (user_id, quietness, seafood, max_activity_limit, crowd_tolerance, energy_level))

    # 2. Create a fresh trip, or clear an existing one for in-place rebuild
    if rebuild:
        cursor.execute("DELETE FROM itinerary_items WHERE trip_id = ?", (trip_id,))
        cursor.execute("DELETE FROM recovery_proposals WHERE trip_id = ?", (trip_id,))
        cursor.execute("DELETE FROM trip_versions WHERE trip_id = ?", (trip_id,))
        cursor.execute("""
        UPDATE trips SET destination = ?, start_date = ?, end_date = ?, current_version = 1, health_score = 92
        WHERE id = ? AND user_id = ?
        """, (destination, start_date, end_date, trip_id, user_id))
    else:
        cursor.execute("""
        INSERT INTO trips (id, user_id, destination, start_date, end_date, health_score, current_version, status)
        VALUES (?, ?, ?, ?, ?, 92, 1, 'ACTIVE')
        """, (trip_id, user_id, destination, start_date, end_date))

    # 4. Fetch & Score All Places
    cursor.execute("SELECT * FROM places")
    all_places = [dict(r) for r in cursor.fetchall()]
    pref_dict = {
        "quietness": quietness,
        "seafood": seafood,
        "budget_max": max_activity_limit,
        "daily_budget": daily_budget,
        "crowd_tolerance": crowd_tolerance,
        "energy_level": energy_level
    }

    scored_places = []
    seen_names_all = set()

    for p in all_places:
        p_name_clean = p['name'].strip().lower()
        if p_name_clean in seen_names_all:
            continue

        res = calculate_place_score(p, pref_dict, origin_area=destination, is_rainy=False, max_radius_km=25.0)
        dist_km = res["distance_km"]

        # HARD CONSTRAINT: Reject extreme distances > 55km to allow reasonable day trips
        if dist_km > 55.0:
            continue

        seen_names_all.add(p_name_clean)
        p_copy = dict(p)
        p_copy["distance_km"] = dist_km
        p_copy["score"] = res["score"]

        # Famous landmark bonus
        if p.get('rating', 0) >= 4.7:
            p_copy["score"] += 5.0

        scored_places.append(p_copy)

    # Sort valid places by score descending
    scored_places.sort(key=lambda x: -x["score"])

    # 5. Dynamic Time Slots & Pacing Logic
    base_slots = []
    if energy_level == 'relaxed':
        base_slots = [("10:00 AM", "Morning"), ("06:30 PM", "Evening")]
    elif energy_level == 'high':
        base_slots = [("08:30 AM", "Morning"), ("01:00 PM", "Afternoon"), ("05:30 PM", "Evening"), ("08:30 PM", "Night")]
    else: # medium
        base_slots = [("09:30 AM", "Morning"), ("02:00 PM", "Afternoon"), ("07:30 PM", "Evening")]

    # Log insight for progressive expansion
    import time
    cursor.execute("""
    INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
    VALUES (?, ?, 'TRIP_INSIGHT', ?, 'engine', 'SUCCESS')
    """, (f"insight_dist_{int(time.time()*1000)}", trip_id, f"Progressive geographic search: Evaluated local clusters and day trips (up to 55km) from {destination}."))

    item_counter = 100
    used_place_names = set()

    # Find indoor fallback
    fallbacks = [p for p in scored_places if p['indoor_flag']]
    fallback_place_id = fallbacks[0]['id'] if fallbacks else "place_22"

    for day in range(1, days_count + 1):
        day_spent = 0
        
        # --- Geographic Day Clustering ---
        available = [p for p in scored_places if p['name'].strip().lower() not in used_place_names]
        
        if not available:
            # We ran out of places. Keep the day genuinely flexible instead of
            # fabricating an item that references a non-existent place.
            cursor.execute("""
            INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
            VALUES (?, ?, 'TRIP_INSIGHT', ?, 'engine', 'SUCCESS')
            """, (f"insight_flex_{day}_{int(time.time()*1000)}", trip_id, f"Candidate Discovery: Insufficient strong matches for Day {day}. This day is kept flexible for spontaneous experiences instead of filling it with weak recommendations."))
            continue
            
        day_anchor = available[0]
            
        anchor_lat = day_anchor.get('lat', 15.5553)
        anchor_lon = day_anchor.get('lon', 73.7517)
        
        # 2. Re-sort available places for THIS DAY to group around the Day Anchor
        available.sort(key=lambda x: (
            haversine_distance(anchor_lat, anchor_lon, x.get('lat', 15.5553), x.get('lon', 73.7517)) - (x.get("score", 0) * 0.1)
        ))

        for slot_time, slot_period in base_slots:
            item_counter += 1
            selected_place = None

            for p in available:
                if p['name'].strip().lower() in used_place_names:
                    continue
                if day_spent + p['price'] <= daily_budget * 1.3 or day_spent == 0:
                    selected_place = p
                    clean_name = p['name'].strip().lower()
                    used_place_names.add(clean_name)
                    day_spent += p.get('price', 0)
                    break

            if not selected_place:
                # If budget constraints blocked everything, just pick the closest one
                for p in available:
                    if p['name'].strip().lower() not in used_place_names:
                        selected_place = p
                        used_place_names.add(p['name'].strip().lower())
                        break
            
            if not selected_place:
                break # out of places for this specific slot

            # Globally unique across trips: scope by trip_id so a new generation
            # never collides with another trip's rows (was f"item_{day}{item_counter}").
            item_id = f"item_{trip_id}_{day}_{item_counter}"
            fb_id = fallback_place_id if not selected_place['indoor_flag'] else None

            cursor.execute("""
            INSERT INTO itinerary_items (id, trip_id, day_number, time_slot, time_period, place_id, status, fallback_place_id, version)
            VALUES (?, ?, ?, ?, ?, ?, 'SCHEDULED', ?, 1)
            """, (item_id, trip_id, day, slot_time, slot_period, selected_place['id'], fb_id))

    # 6. Log Version 1 with a full snapshot for rollback/audit
    cursor.execute("""
    INSERT INTO trip_versions (trip_id, version_number, change_description)
    VALUES (?, 1, ?)
    """, (trip_id, f"Living Itinerary generated for {user_name} at {origin_coord['clean_name']} (Total ₹{total_budget}, ₹{daily_budget}/day)."))

    conn.commit()
    conn.close()
    return {
        "status": "SUCCESS",
        "trip_id": trip_id,
        "user_name": user_name,
        "clean_destination": origin_coord['clean_name'],
        "daily_budget": daily_budget,
        "slots_per_day": len(base_slots),
        "message": f"Generated custom living itinerary for {user_name}!"
    }