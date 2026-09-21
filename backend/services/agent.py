import sys
import os
import json
import re
import time
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection
from services.gis import haversine_distance, GOA_AREA_COORDINATES
from services.rag_service import query_rag_knowledge
from services.goa_brain import get_brain
from services.weather_service import get_live_weather
from services.optimizer import generate_custom_trip

import requests as req_lib

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ─────────────────────────────────────────────────────────────
# TOOL SCHEMAS — Groq reads these and decides which to call
# ─────────────────────────────────────────────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get live real-time weather for any place the user mentions. Use this whenever the user asks about weather, rain, forecast, climate, should I carry umbrella, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "description": "The place/city name to get weather for e.g. 'Baga', 'Palolem', 'Panaji'"}
                },
                "required": ["area"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_places_within_radius",
            "description": "Search our database for real places near the user's destination. Use this when user wants suggestions, asks to find restaurants/beaches/cafes/attractions, or wants to pick an activity to add to the itinerary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "description": "Center area to search near e.g. 'Agonda', 'Panaji'"},
                    "category": {"type": "string", "description": "Category filter e.g. 'Restaurant', 'Beach', 'Museum'. Leave empty for all."},
                    "radius_km": {"type": "number", "description": "Search radius in km. Use 10-15 for local, up to 35 for broader search."},
                    "max_price": {"type": "number", "description": "Maximum price per activity in INR."}
                },
                "required": ["area"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_itinerary",
            "description": "Add or swap a place in the user's itinerary. Use ONLY when user explicitly confirms they want to add a specific place (by name, or by saying 'option 1/2/3', 'the first one', 'add that', 'yes add it', etc.). Must have a real place_id from our database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string", "description": "Always 'trip_1'"},
                    "place_id": {"type": "string", "description": "The exact place ID from our database e.g. 'place_3'. Get this from a prior search_places_within_radius call."},
                    "day_number": {"type": "integer", "description": "Which day to add the activity to (1, 2, 3, etc.)"},
                    "time_slot": {"type": "string", "description": "Time slot e.g. '04:30 PM', '09:30 AM', '07:30 PM'"}
                },
                "required": ["trip_id", "place_id", "day_number", "time_slot"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_itinerary",
            "description": "Remove or cancel an activity from the user's itinerary. Use when user says remove, delete, cancel, drop, or clear an activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string", "description": "Always 'trip_1'"},
                    "day_number": {"type": "integer", "description": "Day number to remove from"},
                    "time_slot": {"type": "string", "description": "Optional: specific time slot to remove e.g. '07:30 PM'"}
                },
                "required": ["trip_id", "day_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "regenerate_trip_budget",
            "description": "Rebuild the entire itinerary with a new budget limit. Use when user says they want to change budget, spend more/less, upgrade to luxury, or reduce costs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string", "description": "Always 'trip_1'"},
                    "daily_budget": {"type": "integer", "description": "New daily budget in INR per activity"},
                    "days": {"type": "integer", "description": "Number of trip days"}
                },
                "required": ["trip_id", "daily_budget", "days"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_host_tip",
            "description": "Get insider local knowledge, host tips, hidden gems, and authentic Goa recommendations from our RAG knowledge base. Use when user asks for local tips, hidden places, authentic experiences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or topic to search local knowledge for"}
                },
                "required": ["query"]
            }
        }
    }
]


# ─────────────────────────────────────────────────────────────
# DETERMINISTIC TOOL EXECUTOR
# ─────────────────────────────────────────────────────────────
def execute_tool(tool_name, tool_args, session_trip_id="trip_1", user=None):
    """
    Executes tool calls requested by the AI agent and returns structured outputs.
    This layer is fully deterministic — no LLM involved here.
    """
    conn = get_connection()
    cursor = conn.cursor()
    result = {}

    if tool_name == "get_weather":
        area = tool_args.get("area", "Goa")
        result = get_live_weather(area=area)

    elif tool_name in ["search_places_within_radius", "search_places"]:
        category = tool_args.get("category", "")
        max_price = tool_args.get("max_price", 5000)
        area = tool_args.get("area", "Goa")
        radius_km = tool_args.get("radius_km", 15.0)

        cursor.execute("SELECT * FROM places WHERE price <= ?", (max_price,))
        all_places = [dict(r) for r in cursor.fetchall()]

        from services.gis import resolve_location_coordinates
        origin_info = resolve_location_coordinates(area)

        matches = []
        for p in all_places:
            if category and category.lower() not in p["category"].lower() and category.lower() not in p["name"].lower():
                continue
            dist_km = haversine_distance(origin_info["lat"], origin_info["lon"], p["lat"], p["lon"])
            if dist_km <= radius_km:
                p_copy = dict(p)
                p_copy["distance_km"] = round(dist_km, 2)
                matches.append(p_copy)

        matches.sort(key=lambda x: x["distance_km"])
        result = {
            "origin_area": area,
            "radius_km": radius_km,
            "matches_count": len(matches),
            "places": matches[:8]
        }

    elif tool_name == "update_itinerary":
        trip_id = session_trip_id  # never trust LLM-supplied trip_id
        day_number = tool_args.get("day_number", 1)
        time_slot = tool_args.get("time_slot", "04:30 PM")
        place_id = tool_args.get("place_id", "")

        cursor.execute("SELECT * FROM itinerary_items WHERE trip_id = ? AND day_number = ? AND time_slot = ?",
                       (trip_id, day_number, time_slot))
        row = cursor.fetchone()

        if row:
            cursor.execute("""
            UPDATE itinerary_items SET place_id = ?, status = 'MODIFIED_BY_AGENT', version = version + 1
            WHERE id = ?
            """, (place_id, row['id']))
        else:
            item_id = f"item_{int(datetime.now().timestamp())}"
            cursor.execute("""
            INSERT INTO itinerary_items (id, trip_id, day_number, time_slot, time_period, place_id, status, version)
            VALUES (?, ?, ?, ?, 'Custom', ?, 'ADDED_BY_AGENT', 1)
            """, (item_id, trip_id, day_number, time_slot, place_id))

        cursor.execute("SELECT name FROM places WHERE id = ?", (place_id,))
        p_row = cursor.fetchone()
        p_name = p_row['name'] if p_row else place_id

        action_id = f"action_{int(time.time() * 1000)}"
        cursor.execute("""
        INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
        VALUES (?, ?, 'UPDATE_ITINERARY', ?, 'update_itinerary', 'SUCCESS')
        """, (action_id, trip_id, f"Added {p_name} to Day {day_number} ({time_slot})"))

        conn.commit()
        result = {"status": "SUCCESS", "added_place": p_name, "day": day_number, "time_slot": time_slot}

    elif tool_name == "remove_itinerary":
        trip_id = session_trip_id  # never trust LLM-supplied trip_id
        day_number = tool_args.get("day_number", 1)
        time_slot = tool_args.get("time_slot")

        if time_slot:
            cursor.execute("""
            UPDATE itinerary_items SET status = 'CANCELLED', version = version + 1
            WHERE trip_id = ? AND day_number = ? AND time_slot = ? AND status != 'CANCELLED'
            """, (trip_id, day_number, time_slot))
        else:
            cursor.execute("""
            UPDATE itinerary_items SET status = 'CANCELLED', version = version + 1
            WHERE trip_id = ? AND day_number = ? AND status != 'CANCELLED'
            """, (trip_id, day_number))

        action_id = f"action_{int(time.time() * 1000)}"
        cursor.execute("""
        INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
        VALUES (?, ?, 'REMOVE_ITINERARY', ?, 'remove_itinerary', 'SUCCESS')
        """, (action_id, trip_id, f"Removed from Day {day_number}" + (f" at {time_slot}" if time_slot else "")))

        conn.commit()
        result = {"status": "SUCCESS", "message": f"Removed activity from Day {day_number}"}

    elif tool_name == "regenerate_trip_budget":
        daily_budget = tool_args.get("daily_budget", 5000)
        days = tool_args.get("days", 4)
        total_b = daily_budget * days
        trip_id_ctx = session_trip_id  # rebuild the SAME trip in place

        cursor.execute("SELECT user_id, destination FROM trips WHERE id = ?", (trip_id_ctx,))
        t_row = cursor.fetchone()
        trip_dest = t_row['destination'] if t_row and t_row['destination'] else "Goa"
        trip_user_id = t_row['user_id'] if t_row and t_row['user_id'] else (user or {}).get("id", "user_guest")

        cursor.execute("SELECT quietness, seafood FROM preferences WHERE user_id = ?", (trip_user_id,))
        p_row = cursor.fetchone()
        quietness_v = p_row['quietness'] if p_row else 0.8
        seafood_v = p_row['seafood'] if p_row else 0.5

        generate_custom_trip(
            user={"id": trip_user_id, "name": (user or {}).get("name", "Traveler")},
            destination=trip_dest,
            days_count=days,
            total_budget=total_b,
            quietness=quietness_v,
            seafood=seafood_v,
            existing_trip_id=trip_id_ctx,
        )
        result = {"status": "SUCCESS", "daily_budget": daily_budget, "total_budget": total_b,
                  "message": f"Itinerary rebuilt for ₹{daily_budget}/day near {trip_dest}."}

    elif tool_name in ["ask_host_tip", "query_rag"]:
        query = tool_args.get("query", "Goa authentic tips")
        hits = get_brain().search(query, top_k=3)
        result = {"rag_hits": [{"title": h["title"], "content": h["content"]} for h in hits]}

    conn.close()
    return result


# ─────────────────────────────────────────────────────────────
# TRIP CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────
def _build_trip_context(trip_id, area):
    lines = [f"Destination: {area}"]
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT p.* FROM preferences p
            JOIN trips t ON t.user_id = p.user_id
            WHERE t.id = ?
        """, (trip_id,))
        pref_row = cur.fetchone()
        if pref_row:
            pref = dict(pref_row)
            lines.append(f"Budget per activity: Rs{pref['budget_max']}")
            lines.append(f"Energy level: {pref.get('energy_level', 'medium')}")
            lines.append(f"Quietness preference: {int(pref['quietness'] * 100)}%")

        cur.execute("""
            SELECT i.day_number, i.time_slot, i.time_period, i.place_id, p.name, p.area, p.category, p.price, p.rating, p.crowd_level
            FROM itinerary_items i JOIN places p ON i.place_id = p.id
            WHERE i.trip_id = ? AND i.status != 'CANCELLED'
            ORDER BY i.day_number, i.time_slot
        """, (trip_id,))
        items = cur.fetchall()
        conn.close()

        if items:
            lines.append("\nCurrent Itinerary (with real place_ids for tool use):")
            cur_day = None
            for row in items:
                if row['day_number'] != cur_day:
                    cur_day = row['day_number']
                    lines.append(f"  Day {cur_day}:")
                lines.append(
                    f"    [{row['place_id']}] {row['time_slot']} ({row['time_period']}): {row['name']} "
                    f"-- {row['area']} [{row['category']}] Rs{row['price']} {row['rating']} Crowd:{row['crowd_level']}"
                )
    except Exception as e:
        print(f"Context build error: {e}")
    return "\n".join(lines)


def _save_search_memory(trip_id: str, places: list):
    """
    Persists the last search results (place_id + name) into agent_actions so the
    next conversation turn can resolve 'option 2' → place_id correctly.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        payload = json.dumps([{"idx": i+1, "id": p["id"], "name": p["name"]} for i, p in enumerate(places[:5])])
        action_id = f"searchmem_{int(time.time()*1000)}"
        # Delete old search memory for this trip first
        cur.execute("DELETE FROM agent_actions WHERE trip_id = ? AND action = 'SEARCH_MEMORY'", (trip_id,))
        cur.execute("""
            INSERT INTO agent_actions (id, trip_id, action, reason, tool_used, status)
            VALUES (?, ?, 'SEARCH_MEMORY', ?, 'search_places_within_radius', 'SUCCESS')
        """, (action_id, trip_id, payload))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Search memory save error: {e}")


def _load_search_memory(trip_id: str) -> str:
    """
    Loads the last search results from DB and formats them as a context block.
    Returns empty string if no memory found.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT reason FROM agent_actions
            WHERE trip_id = ? AND action = 'SEARCH_MEMORY'
            ORDER BY id DESC LIMIT 1
        """, (trip_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            options = json.loads(row['reason'])
            lines = ["[PREVIOUS SEARCH RESULTS — for resolving 'option 1/2/3' references]:"]
            for o in options:
                lines.append(f"  Option {o['idx']}: place_id={o['id']} | Name: {o['name']}")
            lines.append("If user says 'option 2', 'the second one', 'add that', etc., map to the place_id above.")
            return "\n".join(lines)
    except Exception as e:
        print(f"Search memory load error: {e}")
    return ""



# ─────────────────────────────────────────────────────────────
# CORE GROQ CALL — Raw request
# ─────────────────────────────────────────────────────────────
def _call_groq(messages, tools=None, tool_choice="auto", temperature=0.5, max_tokens=600):
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    try:
        resp = req_lib.post(
            GROQ_URL,
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 413:
            # Retry minimal — strip tools and history
            payload["messages"] = [messages[0], messages[-1]]
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
            resp = req_lib.post(GROQ_URL, json=payload,
                                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                                timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Groq API error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# MAIN AGENT — Agentic Tool-Calling Loop
# ─────────────────────────────────────────────────────────────
def run_agent_chat(user_message, trip_id="trip_1", destination=None, history=None, user=None):
    """
    Production-grade agentic loop using Groq native Tool Calling.
    
    Flow:
    1. Build system prompt with full trip context
    2. Call Groq WITH tool schemas — LLM decides which tool (if any) to call
    3. If LLM calls a tool → execute it deterministically → feed result back to LLM
    4. LLM generates final natural-language response grounded in real data
    
    No if/elif keyword matching. The LLM brain decides everything.
    """
    # ── Resolve destination ──────────────────────────────────
    area = destination or "Goa"
    try:
        conn_ctx = get_connection()
        cur_ctx = conn_ctx.cursor()
        cur_ctx.execute("SELECT destination FROM trips WHERE id = ?", (trip_id,))
        t_row = cur_ctx.fetchone()
        if t_row and t_row['destination']:
            area = t_row['destination'].split(',')[0].strip()
        conn_ctx.close()
    except Exception:
        pass

    # ── Goa Brain retrieval (token-optimized RAG) ────────────
    # Instead of dumping the whole places table + knowledge file into the prompt,
    # retrieve ONLY the top-k relevant, budgeted snippets for THIS message.
    brain_str = get_brain().context_block(user_message, top_k=3, max_chars=700)
    rag_hits = [{"title": "GoaBrain", "content": brain_str}] if brain_str else []

    # ── Build trip context ───────────────────────────────────
    trip_context = _build_trip_context(trip_id, area)

    # ── Load search memory (what options were shown last turn) ─
    search_memory = _load_search_memory(trip_id)

    # ── System prompt ────────────────────────────────────────
    system_prompt = (
        "You are Wayzyy TripOS — an intelligent AI travel concierge and operating system for managing live trips.\n"
        "You have access to a set of TOOLS. Use them whenever the user's request requires real data, database actions, or live weather.\n\n"
        "CRITICAL RULES:\n"
        "1. NEVER hallucinate or make up place names, prices, or actions. Only use data returned by tools.\n"
        "2. When adding a place: FIRST call search_places_within_radius to get real place_ids, THEN call update_itinerary.\n"
        "3. When user says 'option 2', 'add that', 'the first one', 'yes go ahead' — look at PREVIOUS SEARCH RESULTS below, get the place_id, and call update_itinerary immediately. Do NOT search again.\n"
        "4. NEVER say 'I added X' unless update_itinerary returned SUCCESS.\n"
        "5. Be multilingual — respond in the same language the user uses.\n"
        "6. Be warm, concise, use emojis naturally.\n\n"
        f"[TRIP CONTEXT]\n{trip_context[:2000]}\n\n"
        + (f"{search_memory}\n\n" if search_memory else "")
        + f"[GOA BRAIN — verified local matches for this request]\n{brain_str or 'None retrieved; call a tool.'}"
    )


    # ── Build message history ────────────────────────────────
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for h in history[-16:]:
            messages.append({"role": h["role"], "content": h["content"][:600]})
    messages.append({"role": "user", "content": user_message})

    # ── STEP 1: First Groq call WITH tools ───────────────────
    response_json = _call_groq(messages, tools=TOOL_SCHEMAS, tool_choice="auto")

    tool_executed = None
    tool_args = {}
    tool_result = {}

    if response_json:
        choice = response_json["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        # ── STEP 2: Did LLM decide to call a tool? ───────────
        if finish_reason == "tool_calls" and message.get("tool_calls"):
            tool_call = message["tool_calls"][0]  # Execute first tool
            tool_executed = tool_call["function"]["name"]
            try:
                tool_args = json.loads(tool_call["function"]["arguments"])
            except Exception:
                tool_args = {}

            print(f"[AGENT] Calling tool: {tool_executed}({tool_args})")
            tool_result = execute_tool(tool_executed, tool_args, session_trip_id=trip_id, user=user)
            print(f"[AGENT] Tool result: {str(tool_result)[:200]}")

            # Save search results to DB so next turn knows what option 1/2/3 are
            if tool_executed in ["search_places_within_radius", "search_places"]:
                _save_search_memory(trip_id, tool_result.get("places", []))


            # ── STEP 3: Feed tool result back to LLM ─────────
            messages.append(message)  # append assistant's tool_call message
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(tool_result)
            })

            # Final LLM call — generate natural response grounded in real tool data
            final_response = _call_groq(messages, tools=None, temperature=0.4, max_tokens=600)
            if final_response:
                reply_text = final_response["choices"][0]["message"]["content"]
            else:
                # Graceful fallback from tool result
                reply_text = _format_tool_fallback(tool_executed, tool_result, tool_args, area)

        else:
            # LLM decided no tool needed — pure conversational answer
            reply_text = message.get("content", "")

    else:
        # Groq completely down — local fallback
        reply_text = (
            f"I'm your Wayzyy TripOS AI for your {area} trip! "
            f"Ask me anything about weather, activities, or your itinerary. 🌍"
        )

    return {
        "reply": reply_text,
        "tool_executed": tool_executed,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "rag_context": rag_hits
    }


def _format_tool_fallback(tool_name, result, args, area):
    """Minimal fallback responses if LLM is down after tool execution."""
    if tool_name == "update_itinerary" and result.get("status") == "SUCCESS":
        return f"✅ Added **{result.get('added_place')}** to Day {result.get('day')} at {result.get('time_slot')}. Refresh the itinerary panel! 📅"
    elif tool_name == "remove_itinerary" and result.get("status") == "SUCCESS":
        return f"✅ Activity removed from your itinerary. Refresh to see the update! 🗑️"
    elif tool_name == "get_weather":
        return f"🌤️ Weather in {result.get('area', area)}: {result.get('condition')} {result.get('temperature_c')}°C. Rain: {result.get('rain_probability')}."
    elif tool_name == "search_places_within_radius":
        places = result.get("places", [])
        if places:
            plist = "\n".join([f"Option {i+1}: **{p['name']}** — {p.get('area','')} ₹{p['price']} ⭐{p['rating']}" for i, p in enumerate(places[:5])])
            return f"📍 Found these places near {area}:\n{plist}\n\nReply 'option 1', 'option 2' etc. to add one."
    elif tool_name == "regenerate_trip_budget":
        return f"💰 Itinerary rebuilt for ₹{args.get('daily_budget')}/day! Refresh your dashboard. ✅"
    return "Done! ✅"


if __name__ == "__main__":
    res = run_agent_chat("on day 1 add one more activity")
    import pprint
    pprint.pprint(res)
