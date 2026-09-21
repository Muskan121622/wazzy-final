import sys
import os
import json
import uuid
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection
from services.gis import haversine_distance, GOA_AREA_COORDINATES
from services.weather_service import get_live_weather

PROPOSAL_TTL_HOURS = 6


# ─────────────────────────────────────────────────────────────
# TIME HELPERS — real schedule math
# ─────────────────────────────────────────────────────────────
def parse_slot_minutes(time_slot: str) -> int:
    """'02:00 PM' / '14:00' → minutes from midnight. Returns -1 if unparseable."""
    try:
        s = (time_slot or "").strip().upper()
        if s.endswith("AM") or s.endswith("PM"):
            meridiem = s[-2:]
            hh, mm = s[:-2].strip().split(":")
            hh, mm = int(hh), int(mm)
            if meridiem == "PM" and hh != 12:
                hh += 12
            if meridiem == "AM" and hh == 12:
                hh = 0
            return hh * 60 + mm
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return -1


def parse_opening_hours(hours_str: str):
    """'09:30 - 17:30' → (570, 1050). '12:00 - 00:00' → (720, 1440). None if missing."""
    try:
        if not hours_str or "-" not in hours_str:
            return None
        open_s, close_s = [p.strip() for p in hours_str.split("-", 1)]
        oh, om = open_s.split(":")
        ch, cm = close_s.split(":")
        open_min = int(oh) * 60 + int(om)
        close_min = int(ch) * 60 + int(cm)
        if close_min <= open_min:
            close_min += 1440  # closes after midnight (e.g. restaurants till 00:00)
        return (open_min, close_min)
    except Exception:
        return None


def is_open_at(hours_str: str, minute_of_day: int) -> bool:
    window = parse_opening_hours(hours_str)
    if not window:
        return True  # unknown hours → assume accessible
    open_min, close_min = window
    probe = minute_of_day if minute_of_day >= open_min else minute_of_day + 1440
    return open_min <= probe < close_min


def _slot_to_hhmm(minutes: int) -> str:
    minutes %= 1440
    if minutes >= 720:
        return f"{((minutes - 720) // 60) or 12:02d}:{minutes % 60:02d} PM"
    return f"{(minutes // 60) or 12:02d}:{minutes % 60:02d} AM"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:8]}"


def _utc_now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────
# SHARED PROPOSAL MECHANICS
# ─────────────────────────────────────────────────────────────
def _load_day_items(cursor, trip_id, day_number):
    cursor.execute("""
    SELECT i.id as item_id, i.day_number, i.time_slot, i.time_period, i.status, i.fallback_place_id,
           p.id as place_id, p.name as place_name, p.indoor_flag, p.area, p.lat, p.lon,
           p.opening_hours, p.category, p.price, p.rating, p.crowd_level, p.plan_b_id
    FROM itinerary_items i
    JOIN places p ON i.place_id = p.id
    WHERE i.trip_id = ? AND i.day_number = ? AND i.status NOT IN ('CANCELLED', 'RECOVERED')
    """, (trip_id, day_number))
    items = [dict(r) for r in cursor.fetchall()]
    items.sort(key=lambda x: max(parse_slot_minutes(x["time_slot"]), 0))
    return items


def _has_pending(cursor, trip_id, item_id) -> bool:
    cursor.execute(
        "SELECT 1 AS x FROM recovery_proposals WHERE trip_id = ? AND original_item_id = ? AND status = 'PENDING'",
        (trip_id, item_id),
    )
    return cursor.fetchone() is not None


def _expire_stale(cursor, trip_id):
    cursor.execute(
        "UPDATE recovery_proposals SET status = 'EXPIRED' WHERE trip_id = ? AND status = 'PENDING' AND expires_at IS NOT NULL AND expires_at < ?",
        (trip_id, _utc_now_str()),
    )


def _find_open_alternative(cursor, area, at_minute, prefer_indoor, exclude_ids, max_km=25.0):
    """Nearest non-conflicting place, open at the given minute, matching indoor preference."""
    from services.gis import resolve_location_coordinates
    origin = resolve_location_coordinates(area)

    cursor.execute("SELECT * FROM places")
    candidates = [dict(r) for r in cursor.fetchall()]

    scored = []
    for c in candidates:
        if c["id"] in exclude_ids:
            continue
        if prefer_indoor and not c["indoor_flag"]:
            continue
        if not is_open_at(c.get("opening_hours"), at_minute):
            continue
        dist = haversine_distance(origin["lat"], origin["lon"], c.get("lat") or 15.55, c.get("lon") or 73.75)
        if dist > max_km:
            continue
        # same-area bonus, then distance & rating
        area_bonus = 0 if (c.get("area") or "").lower() == (area or "").lower() else 8.0
        scored.append((dist + area_bonus - (c.get("rating") or 4) * 2, c))
    scored.sort(key=lambda x: x[0])
    return scored[0][1] if scored else None


def _insert_proposal(cursor, trip_id, trip_version, item_id, place_id, reason, ptype, score, proposed_time_slot=None):
    proposal_id = _new_id("prop")
    expires = (datetime.utcnow() + timedelta(hours=PROPOSAL_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO recovery_proposals (id, trip_id, trip_version, original_item_id, proposed_place_id, proposed_time_slot, type, reason, score, status, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
    """, (proposal_id, trip_id, trip_version, item_id, place_id, proposed_time_slot, ptype, reason, score, expires))
    return proposal_id


def _log_incident(cursor, trip_id, itype, detail, severity="INFO"):
    cursor.execute(
        "INSERT INTO incidents (id, trip_id, type, detail, severity) VALUES (?, ?, ?, ?, ?)",
        (_new_id("inc"), trip_id, itype, detail, severity),
    )


# ─────────────────────────────────────────────────────────────
# 1. WEATHER RECOVERY (guarded by LIVE weather, deduped, expiring)
# ─────────────────────────────────────────────────────────────
def create_recovery_proposal(trip_id, day_number=1, condition="WEATHER_ALERT"):
    """
    Weather incident → PENDING swap proposals for outdoor items.
    Hard guard: proposals are ONLY created when the LIVE forecast actually says rain.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT destination, current_version, user_id FROM trips WHERE id = ?", (trip_id,))
        trip_row = cursor.fetchone()
        if not trip_row:
            return {"status": "TRIP_NOT_FOUND"}

        dest_str = trip_row["destination"]
        curr_version = trip_row["current_version"]

        dest_area = "Baga"
        for area_key in GOA_AREA_COORDINATES.keys():
            if area_key.lower() in (dest_str or "").lower():
                dest_area = area_key
                break

        weather_info = get_live_weather(area=dest_area)

        # LIVE-WEATHER GUARD: never propose rain swaps on a sunny day
        if not weather_info.get("is_rainy"):
            _log_incident(cursor, trip_id, "WEATHER_CHECK", f"Live weather in {dest_area}: {weather_info['condition']} — no action needed.")
            conn.commit()
            return {
                "status": "NO_ACTION_REQUIRED",
                "condition": weather_info["condition"],
                "proposal_count": 0,
                "swapped_details": [],
                "why_audit": f"Live Open-Meteo check for {dest_area} reports '{weather_info['condition']}' (rain probability {weather_info['rain_probability']}). Itinerary left untouched.",
            }

        _expire_stale(cursor, trip_id)
        items = _load_day_items(cursor, trip_id, day_number)
        exclude_ids = {it["place_id"] for it in items}

        proposals = []
        for item in items:
            if item["indoor_flag"] or _has_pending(cursor, trip_id, item["item_id"]):
                continue

            slot_min = max(parse_slot_minutes(item["time_slot"]), 0)
            fallback_place = None
            for fb_id in (item["fallback_place_id"], item["plan_b_id"]):
                if not fb_id:
                    continue
                cursor.execute("SELECT * FROM places WHERE id = ?", (fb_id,))
                fb = cursor.fetchone()
                if fb and fb["indoor_flag"] and is_open_at(fb["opening_hours"], slot_min):
                    fallback_place = dict(fb)
                    break
            if not fallback_place:
                fallback_place = _find_open_alternative(cursor, item["area"], slot_min, prefer_indoor=True, exclude_ids=exclude_ids | {item["place_id"]})
            if not fallback_place:
                continue

            proposal_id = _insert_proposal(
                cursor, trip_id, curr_version, item["item_id"], fallback_place["id"],
                reason=(
                    f"Live Open-Meteo alert: {weather_info['rain_probability']} rain probability in {dest_area} "
                    f"({weather_info['condition']}). Swap outdoor {item['place_name']} ({item['time_slot']}) for "
                    f"{fallback_place['name']} ({fallback_place['area']} · indoor · open at this slot)."
                ),
                ptype="WEATHER", score=91.5,
            )
            exclude_ids.add(fallback_place["id"])
            proposals.append({
                "proposal_id": proposal_id,
                "trip_version": curr_version,
                "original_place": item["place_name"],
                "new_place": fallback_place["name"],
                "new_place_area": fallback_place["area"],
                "time_slot": item["time_slot"],
                "day_number": item["day_number"],
                "type": "WEATHER",
                "reason": f"Rain probability {weather_info['rain_probability']} in {dest_area}",
            })

        _log_incident(cursor, trip_id, "WEATHER_ALERT", f"{weather_info['condition']} ({weather_info['rain_probability']}) in {dest_area}; {len(proposals)} proposal(s) raised.", severity="WARNING" if proposals else "INFO")
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "PROPOSAL_CREATED" if proposals else "NO_ACTION_REQUIRED",
        "condition": weather_info["condition"],
        "proposal_count": len(proposals),
        "swapped_details": proposals,
        "why_audit": (
            f"Live Open-Meteo forecast: {weather_info['condition']} in {dest_area} "
            f"(rain probability {weather_info['rain_probability']}). Only outdoor, currently-unproposed items "
            f"received rain-safe indoor alternatives that are verified open at their time slot."
        ),
    }


# ─────────────────────────────────────────────────────────────
# 2. DELAY / TRAFFIC ENGINE (real arrival-time vs schedule vs hours)
# ─────────────────────────────────────────────────────────────
def evaluate_schedule_delay(trip_id, day_number=1, delayed_item_id=None, delay_minutes=45,
                            user_lat=None, user_lon=None, speed_kmh=25.0, current_time=None):
    """
    GPS- and time-aware delay engine.

    Live mode (client sends current_time + user GPS):
        arrival = now + travel_time(user's live position -> next item)
        lateness = arrival - next scheduled slot
    Estimate mode (no current_time, e.g. a traffic alert gives a delay figure):
        arrival = next_slot + delay_minutes + travel_time(curr stop -> next)

    In BOTH modes travel time is measured from the user's actual GPS when
    provided, never from a fixed constant. A conflict fires when the traveller
    arrives >45 min past the next slot, OR the place would already be closed
    on arrival. Proposes a swap to a nearby open place, or a pure time-shift.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT current_version FROM trips WHERE id = ?", (trip_id,))
        trip_row = cursor.fetchone()
        if not trip_row:
            return {"status": "TRIP_NOT_FOUND"}
        curr_ver = trip_row["current_version"]

        items = _load_day_items(cursor, trip_id, day_number)
        if len(items) < 2:
            return {"status": "NO_CONFLICT", "message": "Fewer than 2 items scheduled for this day."}

        curr_item, next_item, found = items[0], items[1], False
        if delayed_item_id:
            for idx, item in enumerate(items):
                if item["item_id"] == delayed_item_id:
                    found = True
                    if idx + 1 >= len(items):
                        return {"status": "ON_SCHEDULE", "message": "Delayed item is the last stop of the day — nothing downstream to protect."}
                    curr_item, next_item = item, items[idx + 1]
                    break
        if not found:
            # default: assume traveler is delayed at the first stop
            curr_item, next_item = items[0], items[1]

        # Current position: live GPS wins, else the stop they're assumed to be at.
        has_gps = user_lat is not None and user_lon is not None
        curr_lat = user_lat if has_gps else curr_item["lat"]
        curr_lon = user_lon if has_gps else curr_item["lon"]

        dist_km = haversine_distance(curr_lat, curr_lon, next_item["lat"], next_item["lon"])
        travel_time_min = (dist_km / max(speed_kmh, 5.0)) * 60.0

        next_slot = parse_slot_minutes(next_item["time_slot"])
        next_slot = next_slot if next_slot >= 0 else 12 * 60
        now_min = parse_slot_minutes(current_time) if current_time else None

        if now_min is not None:
            # LIVE mode: anchored to the traveller's actual clock time.
            mode = "live"
            arrival = now_min + travel_time_min
        else:
            # ESTIMATE mode: anchored to schedule + a reported delay figure.
            mode = "estimate"
            arrival = next_slot + delay_minutes + travel_time_min

        lateness = arrival - next_slot

        hours = parse_opening_hours(next_item["opening_hours"])
        closed_on_arrival = hours is not None and not is_open_at(next_item["opening_hours"], int(arrival) % 1440)
        late_conflict = lateness > 45.0
        has_conflict = late_conflict or closed_on_arrival

        base = {
            "mode": mode,
            "position_source": "gps" if has_gps else "current_stop",
            "current_time": _slot_to_hhmm(int(now_min) % 1440) if now_min is not None else None,
            "delay_minutes": delay_minutes if mode == "estimate" else 0,
            "distance_km": round(dist_km, 2),
            "travel_time_min": round(travel_time_min, 1),
            "arrival_slot": _slot_to_hhmm(int(arrival) % 1440),
            "lateness_min": round(max(lateness, 0), 1),
            "next_place": next_item["place_name"],
            "next_slot": next_item["time_slot"],
            "next_closes": (f"{hours[1] % 1440 // 60:02d}:{hours[1] % 1440 % 60:02d}" if hours else None),
            "closed_on_arrival": closed_on_arrival,
        }

        proposal_details = None
        if has_conflict and not _has_pending(cursor, trip_id, next_item["item_id"]):
            alt = _find_open_alternative(
                cursor, next_item["area"], int(arrival) % 1440,
                prefer_indoor=False,
                exclude_ids={it["place_id"] for it in items} | {next_item["place_id"]},
                max_km=15.0,
            ) if closed_on_arrival else None

            pos_note = "from your live location" if has_gps else "from current stop"
            if now_min is not None:
                lateness_note = f"at {base['current_time']} you're running {lateness:.0f} min behind schedule"
            else:
                lateness_note = f"running {delay_minutes} min late"

            if alt:
                reason = (
                    f"Delay math ({pos_note}): {lateness_note}; ~{travel_time_min:.0f} min travel, "
                    f"arrival at {next_item['place_name']} ≈ {base['arrival_slot']} but it closes at {base['next_closes']}. "
                    f"Swap to {alt['name']} ({alt['area']}) which is open at that time."
                )
                proposal_id = _insert_proposal(cursor, trip_id, curr_ver, next_item["item_id"], alt["id"], reason, "DELAY", 88.0)
                proposal_details = {"proposal_id": proposal_id, "action": "SWAP", "replacement": alt["name"], "reason": reason}
            else:
                new_slot = base["arrival_slot"]
                reason = (
                    f"Delay math ({pos_note}): {lateness_note}; ~{travel_time_min:.0f} min travel → "
                    f"arriving ~{new_slot} ({lateness:.0f} min past schedule). Shift {next_item['place_name']} to {new_slot}."
                )
                proposal_id = _insert_proposal(cursor, trip_id, curr_ver, next_item["item_id"], next_item["place_id"], reason, "DELAY", 85.0, proposed_time_slot=new_slot)
                proposal_details = {"proposal_id": proposal_id, "action": "SHIFT", "new_time_slot": new_slot, "reason": reason}

            _log_incident(cursor, trip_id, "DELAY_CONFLICT", f"{next_item['place_name']}: late {lateness:.0f} min, closed_on_arrival={closed_on_arrival}, mode={mode}.", severity="WARNING")
            conn.commit()
    finally:
        conn.close()

    return {
        "status": "CONFLICT_DETECTED" if has_conflict else "ON_SCHEDULE",
        **base,
        "proposal": proposal_details,
    }


# ─────────────────────────────────────────────────────────────
# 3. PLACE-CLOSES DETECTION (opening_hours vs scheduled slot)
# ─────────────────────────────────────────────────────────────
def check_closed_places(trip_id, day_number=1):
    """
    Scans a day's schedule and flags any item whose time slot falls OUTSIDE
    the place's opening hours (machine-parsed from 'HH:MM - HH:MM').
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT current_version FROM trips WHERE id = ?", (trip_id,))
        trip_row = cursor.fetchone()
        if not trip_row:
            return {"status": "TRIP_NOT_FOUND"}
        curr_ver = trip_row["current_version"]

        _expire_stale(cursor, trip_id)
        items = _load_day_items(cursor, trip_id, day_number)
        proposals = []

        for item in items:
            slot_min = parse_slot_minutes(item["time_slot"])
            if slot_min < 0 or _has_pending(cursor, trip_id, item["item_id"]):
                continue
            if is_open_at(item["opening_hours"], slot_min):
                continue

            alt = _find_open_alternative(
                cursor, item["area"], slot_min,
                prefer_indoor=bool(item["indoor_flag"]),
                exclude_ids={it["place_id"] for it in items} | {item["place_id"]},
            )
            if not alt:
                continue

            reason = (
                f"Closing-Hours Alert: {item['place_name']} is only open {item['opening_hours']}, "
                f"but it is scheduled at {item['time_slot']}. Replace with {alt['name']} ({alt['area']}), "
                f"open at this time (rating {alt['rating']})."
            )
            proposal_id = _insert_proposal(cursor, trip_id, curr_ver, item["item_id"], alt["id"], reason, "CLOSED_PLACE", 90.0)
            proposals.append({
                "proposal_id": proposal_id,
                "closed_place": item["place_name"],
                "hours": item["opening_hours"],
                "time_slot": item["time_slot"],
                "replacement": alt["name"],
                "type": "CLOSED_PLACE",
            })

        if proposals:
            _log_incident(cursor, trip_id, "CLOSED_PLACE", f"{len(proposals)} item(s) scheduled outside opening hours.", severity="WARNING")
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "PROPOSAL_CREATED" if proposals else "ALL_PLACES_OPEN",
        "proposal_count": len(proposals),
        "details": proposals,
    }


# ─────────────────────────────────────────────────────────────
# 4. APPROVAL — atomic compare-and-swap versioning
# ─────────────────────────────────────────────────────────────
def _trip_snapshot(cursor, trip_id) -> str:
    cursor.execute("""
    SELECT i.day_number, i.time_slot, i.time_period, i.status, p.name as place
    FROM itinerary_items i JOIN places p ON i.place_id = p.id
    WHERE i.trip_id = ? ORDER BY i.day_number, i.time_slot
    """, (trip_id,))
    return json.dumps([dict(r) for r in cursor.fetchall()])


def _recompute_health(cursor, trip_id) -> int:
    cursor.execute("SELECT COUNT(*) as c FROM recovery_proposals WHERE trip_id = ? AND status = 'PENDING'", (trip_id,))
    pending = (cursor.fetchone() or {}).get("c", 0) or 0
    cursor.execute("SELECT COUNT(*) as c FROM incidents WHERE trip_id = ? AND severity = 'WARNING'", (trip_id,))
    warnings = (cursor.fetchone() or {}).get("c", 0) or 0
    return max(55, 100 - pending * 4 - min(warnings * 2, 12))


def approve_recovery_proposal(proposal_id, user_id=None):
    """
    Applies a PENDING proposal with optimistic concurrency:
    the version bump is a single atomic compare-and-swap UPDATE,
    so two simultaneous approvals can never both win.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recovery_proposals WHERE id = ?", (proposal_id,))
        proposal_row = cursor.fetchone()
        if not proposal_row:
            return {"status": "ERROR", "message": "Recovery proposal not found"}
        proposal = dict(proposal_row)
        trip_id = proposal["trip_id"]  # never trust a client-passed trip for this mutation

        cursor.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
        trip = cursor.fetchone()
        if not trip:
            return {"status": "ERROR", "message": "Trip not found"}
        if user_id and trip["user_id"] != user_id:
            return {"status": "FORBIDDEN", "message": "This proposal belongs to another user's trip"}

        if proposal["status"] != "PENDING":
            return {"status": "ALREADY_PROCESSED", "message": f"Proposal already {proposal['status']}"}
        if proposal.get("expires_at") and str(proposal["expires_at"]) < _utc_now_str():
            cursor.execute("UPDATE recovery_proposals SET status = 'EXPIRED' WHERE id = ?", (proposal_id,))
            conn.commit()
            return {"status": "EXPIRED", "message": "This proposal expired and no longer matches live conditions."}

        curr_ver = trip["current_version"]
        if proposal["trip_version"] != curr_ver:
            cursor.execute("UPDATE recovery_proposals SET status = 'EXPIRED' WHERE id = ?", (proposal_id,))
            conn.commit()
            return {
                "status": "STALE_PROPOSAL_REJECTED",
                "message": f"Proposal was built on v{proposal['trip_version']} but trip is now v{curr_ver}. Rejected safely.",
            }

        # ATOMIC compare-and-swap: only one concurrent approver can win
        new_ver = curr_ver + 1
        cursor.execute("UPDATE trips SET current_version = ? WHERE id = ? AND current_version = ?", (new_ver, trip_id, curr_ver))
        if cursor.rowcount != 1:
            conn.rollback()
            return {"status": "CONFLICT_RETRY", "message": "Trip was modified concurrently. Please retry approval."}

        # Apply mutation (place swap and/or time shift)
        if proposal.get("proposed_place_id"):
            cursor.execute("""
            UPDATE itinerary_items
            SET place_id = ?, status = 'RECOVERED', version = version + 1
            WHERE id = ?
            """, (proposal["proposed_place_id"], proposal["original_item_id"]))
        if proposal.get("proposed_time_slot"):
            cursor.execute("""
            UPDATE itinerary_items
            SET time_slot = ?, status = 'RECOVERED', version = version + 1
            WHERE id = ?
            """, (proposal["proposed_time_slot"], proposal["original_item_id"]))

        cursor.execute("UPDATE recovery_proposals SET status = 'APPROVED' WHERE id = ?", (proposal_id,))

        cursor.execute("SELECT name FROM places WHERE id = ?", (proposal.get("proposed_place_id"),))
        p_row = cursor.fetchone()
        reason = (
            f"Approved {proposal.get('type') or 'WEATHER'} proposal {proposal_id}: "
            + (f"swapped in {p_row['name'] if p_row else proposal.get('proposed_place_id')}" if proposal.get("proposed_place_id") else "no place change")
            + (f", moved to {proposal['proposed_time_slot']}" if proposal.get("proposed_time_slot") else "")
        )

        cursor.execute("""
        INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
        VALUES (?, ?, 'APPROVE_RECOVERY', ?, 'approve_recovery_proposal', 'SUCCESS')
        """, (_new_id("action"), trip_id, reason))

        health = _recompute_health(cursor, trip_id)
        cursor.execute("UPDATE trips SET health_score = ? WHERE id = ?", (health, trip_id))
        cursor.execute("""
        INSERT INTO trip_versions (trip_id, version_number, change_description, snapshot_json)
        VALUES (?, ?, ?, ?)
        """, (trip_id, new_ver, reason, _trip_snapshot(cursor, trip_id)))

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "SUCCESS",
        "trip_version": new_ver,
        "health_score": health,
        "message": f"Recovery approved! Trip committed to v{new_ver}.",
    }


def reject_recovery_proposal(proposal_id, user_id=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recovery_proposals WHERE id = ?", (proposal_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "ERROR", "message": "Recovery proposal not found"}
        if user_id:
            cursor.execute("SELECT user_id FROM trips WHERE id = ?", (row["trip_id"],))
            t = cursor.fetchone()
            if not t or t["user_id"] != user_id:
                return {"status": "FORBIDDEN", "message": "This proposal belongs to another user's trip"}
        if row["status"] != "PENDING":
            return {"status": "ALREADY_PROCESSED", "message": f"Proposal already {row['status']}"}
        cursor.execute("UPDATE recovery_proposals SET status = 'REJECTED' WHERE id = ?", (proposal_id,))
        cursor.execute("""
        INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
        VALUES (?, ?, 'REJECT_RECOVERY', ?, 'reject_recovery_proposal', 'SUCCESS')
        """, (_new_id("action"), row["trip_id"], f"User rejected proposal {proposal_id} ({row.get('type') or 'WEATHER'})"))
        conn.commit()
    finally:
        conn.close()
    return {"status": "SUCCESS", "message": "Proposal rejected; original plan kept."}


# ─────────────────────────────────────────────────────────────
# 5. READ API for the frontend (proactive delivery)
# ─────────────────────────────────────────────────────────────
def get_pending_proposals(trip_id, user_id=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if user_id:
            cursor.execute("SELECT user_id FROM trips WHERE id = ?", (trip_id,))
            t = cursor.fetchone()
            if not t or t["user_id"] != user_id:
                return {"proposals": [], "count": 0, "status": "FORBIDDEN"}
        _expire_stale(cursor, trip_id)
        cursor.execute("""
        SELECT rp.id, rp.type, rp.reason, rp.score, rp.status, rp.trip_version, rp.expires_at,
               rp.proposed_time_slot,
               i.day_number, i.time_slot as current_slot,
               orig.name as current_place, prop.name as proposed_place, prop.area as proposed_area
        FROM recovery_proposals rp
        JOIN itinerary_items i ON rp.original_item_id = i.id
        LEFT JOIN places orig ON i.place_id = orig.id
        LEFT JOIN places prop ON rp.proposed_place_id = prop.id
        WHERE rp.trip_id = ? AND rp.status = 'PENDING'
        ORDER BY rp.created_at DESC
        """, (trip_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.commit()  # persist any expirations just applied
    finally:
        conn.close()
    return {"proposals": rows, "count": len(rows)}
