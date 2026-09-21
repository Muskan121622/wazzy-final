"""
Extract real Points-of-Interest from goa.pbf (OpenStreetMap) and merge them into
the `places` table so the Goa Brain + recovery engines work with hundreds of
verified locations, not just the 27 curated rows.

Requires: pip install osmium  (needs system libosmium; skip gracefully if absent)

Usage:  python data/extract_pbf.py            # dry run (prints what it would add)
        python data/extract_pbf.py --commit   # actually insert into DB
"""
import os
import re
import sys
import json
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection

PBF_PATH = os.path.join(os.path.dirname(__file__), "..", "goa.pbf")

# Goa bounding box (approx, lat/lon)
BBOX = (73.58, 14.85, 74.10, 15.80)  # min_lon, min_lat, max_lon, max_lat

# OSM tag → our category, and indoor/outdoor
CATEGORY_MAP = {
    "tourism": {
        "museum": ("Indoor/Culture", True), "gallery": ("Indoor/Culture", True),
        "attraction": ("Sightseeing", False), "viewpoint": ("Sightseeing", False),
        "fort": ("Sightseeing", False), "artwork": ("Indoor/Culture", True),
        "zoo": ("Sightseeing", False), "aquarium": ("Indoor/Culture", True),
    },
    "amenity": {
        "restaurant": ("Restaurant", True), "cafe": ("Restaurant", True),
        "fast_food": ("Restaurant", True), "bar": ("Restaurant", True),
        "pub": ("Restaurant", True), "place_of_worship": ("Indoor/Culture", True),
    },
    "shop": {
        "mall": ("Market", True), "supermarket": ("Market", True),
        "gift": ("Market", True), "handicraft": ("Market", True),
    },
    "historic": {
        "monument": ("Sightseeing", False), "ruins": ("Sightseeing", False),
        "fort": ("Sightseeing", False), "church": ("Indoor/Culture", True),
    },
}

_HOURS_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def normalize_hours(raw):
    """Extract 'HH:MM - HH:MM' from an OSM opening_hours string if possible."""
    if not raw:
        return ""
    m = _HOURS_RE.search(raw)
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)} - {int(m.group(3)):02d}:{m.group(4)}"


def in_bbox(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def classify(tags):
    for key, mapping in CATEGORY_MAP.items():
        val = tags.get(key)
        if val and val in mapping:
            return mapping[val]
    if tags.get("natural") == "beach":
        return ("Beach", False)
    return (None, None)


def extract():
    try:
        import osmium
    except Exception:
        print("[extract_pbf] 'osmium' not available. Install with: pip install osmium "
              "(requires system libosmium). Aborting PBF ingest — curated + HF/Kaggle places still work.")
        return []

    class POIHandler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.found = {}

        def _add(self, osm_id, kind, tags, lon, lat):
            cat, indoor = classify(tags)
            if not cat:
                return
            name = tags.get("name")
            if not name or not in_bbox(lon, lat):
                return
            key = name.strip().lower()
            if key in self.found:
                return
            self.found[key] = {
                "id": f"osm_{kind}_{osm_id}",
                "name": name.strip(),
                "area": tags.get("addr:suburb") or tags.get("addr:city") or tags.get("tourism") or "Goa",
                "category": cat,
                "indoor_flag": indoor,
                "crowd_level": "Medium",
                "price": int(re.sub(r"\D", "", tags.get("charge", "") or tags.get("fee", "") or "0") or 0),
                "rating": 4.3,
                "opening_hours": normalize_hours(tags.get("opening_hours")),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "source": "OpenStreetMap (goa.pbf)",
                "description": tags.get("description") or f"{cat} in {name.strip()}, Goa.",
                "plan_b_id": None,
            }

        def node(self, n):
            if n.location.valid():
                self._add(n.id, "n", n.tags, n.location.lon, n.location.lat)

        def way(self, w):
            # pyosmium 4.x: a Way has no .bounds — centroid it from its node locations.
            locs = [
                (n.location.lon, n.location.lat)
                for n in w.nodes
                if n.location and n.location.valid()
            ]
            if not locs:
                return
            lon = sum(x for x, _ in locs) / len(locs)
            lat = sum(y for _, y in locs) / len(locs)
            self._add(w.id, "w", w.tags, lon, lat)

    if not os.path.exists(PBF_PATH):
        print(f"[extract_pbf] {PBF_PATH} not found.")
        return []

    h = POIHandler()
    h.apply_file(PBF_PATH, locations=True)
    print(f"[extract_pbf] Extracted {len(h.found)} candidate POIs from goa.pbf")
    return list(h.found.values())


def merge(commit=False, limit=None):
    pois = extract()
    if not pois:
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM places")
    existing = {r["name"].strip().lower() for r in cur.fetchall()}

    added = 0
    for p in pois:
        if p["name"].strip().lower() in existing:
            continue
        if limit and added >= limit:
            break
        if commit:
            cur.execute("""
            INSERT INTO places (id, name, area, category, indoor_flag, crowd_level, price, rating, opening_hours, lat, lon, source, description, plan_b_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """, (p["id"], p["name"], p["area"], p["category"], bool(p["indoor_flag"]),
                  p["crowd_level"], p["price"], p["rating"], p["opening_hours"], p["lat"], p["lon"],
                  p["source"], p["description"], p["plan_b_id"]))
        existing.add(p["name"].strip().lower())
        added += 1
        if not commit:
            print(f"  would add: {p['name']} ({p['category']}, {p['area']}) hours='{p['opening_hours']}'")

    if commit:
        conn.commit()
    conn.close()
    print(f"[extract_pbf] {'COMMITTED' if commit else 'DRY RUN'}: {added} new OSM places (deduped against existing).")
    if commit and added:
        # Force Goa Brain index rebuild on next startup
        idx = os.path.join(os.path.dirname(__file__), "goa_brain_index.json")
        if os.path.exists(idx):
            os.remove(idx)
            print("[extract_pbf] cleared goa_brain_index.json — will rebuild on startup.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Actually write to DB (default is dry run)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    merge(commit=args.commit, limit=args.limit)
