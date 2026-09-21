"""
Turn the raw goa.pbf into an openable GeoJSON for demos (recruiter walkthroughs).

It reuses the same classify/bbox logic as extract_pbf.py, so the points on the
map are exactly the POIs that get merged into the `places` table / Goa Brain.

Usage:  python data/pbf_to_geojson.py            # writes data/goa_pbf_pois.geojson
        python data/pbf_to_geojson.py --limit 200
Then drag data/goa_pbf_pois.geojson onto https://geojson.io or https://mapshaper.org
"""
import os
import sys
import json
import argparse
from collections import Counter

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import extract_pbf  # noqa: E402  (reuses extract()/classify()/BBOX)

OUT = os.path.join(os.path.dirname(__file__), "goa_pbf_pois.geojson")


def main(limit=None):
    pois = extract_pbf.extract()
    if not pois:
        print("No POIs extracted (osmium missing or pbf not found).")
        return

    if limit:
        pois = pois[:limit]

    feats = []
    for p in pois:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
            "properties": {
                "name": p["name"],
                "category": p["category"],
                "area": p["area"],
                "indoor": p["indoor_flag"],
                "rating": p["rating"],
                "opening_hours": p["opening_hours"],
                "source": p["source"],
            },
        })

    fc = {"type": "FeatureCollection", "features": feats}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)

    print(f"\n[geojson] wrote {len(feats)} POIs -> {OUT}")
    print("[geojson] category breakdown:")
    for cat, n in Counter(p["category"] for p in pois).most_common():
        print(f"   {n:5d}  {cat}")
    print("\nNow open it at https://geojson.io or https://mapshaper.org (drag & drop the file).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    main(limit=ap.parse_args().limit)
