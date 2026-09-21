"""
Bulk-load OSM POIs from goa.pbf into the `places` table FAST.

The plain `extract_pbf.py --commit` inserts row-by-row, which is painfully slow
against a remote Neon endpoint (one network round-trip per row). This uses
psycopg2 execute_values() to send the whole batch in a handful of round-trips.

Usage:  python data/load_pbf.py            # bulk insert all deduped POIs
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import extract_pbf  # noqa: E402  (reuse extract() for parsing + classification)
from database.db import get_connection, IS_POSTGRES, DATABASE_URL  # noqa: E402

COLUMNS = ("id", "name", "area", "category", "indoor_flag", "crowd_level", "price",
           "rating", "opening_hours", "lat", "lon", "source", "description", "plan_b_id")


def _rows(pois):
    return [
        (p["id"], p["name"], p["area"], p["category"], bool(p["indoor_flag"]), p["crowd_level"],
         p["price"], p["rating"], p["opening_hours"], p["lat"], p["lon"],
         p["source"], p["description"], p["plan_b_id"])
        for p in pois
    ]


def main():
    pois = extract_pbf.extract()
    if not pois:
        print("No POIs extracted (osmium missing or pbf not found).")
        return

    # Dedup against existing place names (case-insensitive), matching extract_pbf's rule.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM places")
    existing = {r["name"].strip().lower() for r in cur.fetchall()}
    new = [p for p in pois if p["name"].strip().lower() not in existing]
    conn.close()
    print(f"[load_pbf] {len(pois)} parsed, {len(new)} new (after dedup against {len(existing)} existing)")
    if not new:
        print("[load_pbf] nothing to insert.")
        return

    rows = _rows(new)
    cols = ", ".join(COLUMNS)
    ph = ", ".join(["%s"] * len(COLUMNS))
    sql = f"INSERT INTO places ({cols}) VALUES %s ON CONFLICT (id) DO NOTHING"

    if IS_POSTGRES:
        import psycopg2
        from psycopg2.extras import execute_values
        kw = {} if "sslmode" in DATABASE_URL.lower() else {"sslmode": "prefer"}
        pg = psycopg2.connect(DATABASE_URL, connect_timeout=15, **kw)
        try:
            with pg.cursor() as c:
                execute_values(c, sql, rows, template=f"({ph})", page_size=2000)
            pg.commit()
        finally:
            pg.close()
    else:
        conn = get_connection()
        cur = conn.cursor()
        # convert %s placeholders -> ? for the sqlite adapter
        cur.executemany(sql.replace("%s", "?"), rows)
        conn.commit()
        conn.close()

    # Force Goa-Brain rebuild on next startup.
    idx = os.path.join(os.path.dirname(__file__), "goa_brain_index.json")
    if os.path.exists(idx):
        os.remove(idx)
    print(f"[load_pbf] INSERTED {len(rows)} OSM places; cleared goa_brain_index.json.")


if __name__ == "__main__":
    main()
