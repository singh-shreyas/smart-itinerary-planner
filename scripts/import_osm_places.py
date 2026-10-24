"""Optional: list named food and shopping places for one city from OpenStreetMap (needs internet).

    python scripts/import_osm_places.py mathura --radius 5 > review.csv

This is the "import more later" path for food and shopping. It is NOT run by
the web app and it does NOT write into data/: the output is a CSV for a person
to review, after which chosen rows can be copied into data/curation/food_shopping.csv
(or straight into data/attractions.csv with their sources).

Source: the public Overpass API over OpenStreetMap data.
  Licence:   ODbL 1.0 -- attribution "© OpenStreetMap contributors" is required, and a
             database built from it must stay under the ODbL (share-alike).
  Limits:    fair use of the public server -- roughly 10,000 queries a day and 1-2 parallel
             requests; heavy users should run their own Overpass instance.
  Coverage:  restaurants, cafés, marketplaces and malls are widely mapped in Indian cities,
             but opening_hours, cuisine and diet:vegetarian tags are often missing. When a
             tag is missing the column is left empty -- nothing is guessed.
  Setup:     none (no API key). A descriptive User-Agent is sent (scripts/net.py).

Only places with a name are listed. Columns: name, kind, lat, lng, cuisine,
vegetarian (OSM diet:vegetarian = only/yes -> yes, else empty), opening_hours, osm id.
"""

import argparse
import csv
import json
import os
import sys

from net import get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERPASS = "https://overpass-api.de/api/interpreter"
KINDS = {"restaurant": "food", "cafe": "food", "fast_food": "food", "marketplace": "market", "mall": "mall",
         "bakery": "food", "confectionery": "food"}


def city_centre(slug):
    with open(os.path.join(ROOT, "data", "cities.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["slug"] == slug:
                return float(row["center_lat"]), float(row["center_lng"])
    raise SystemExit(f"unknown city {slug}")


def query(lat, lng, radius_km):
    r = int(radius_km * 1000)
    q = (f'[out:json][timeout:60];('
         f'nwr["amenity"~"^(restaurant|cafe|fast_food|marketplace)$"]["name"](around:{r},{lat},{lng});'
         f'nwr["shop"~"^(mall|bakery|confectionery)$"]["name"](around:{r},{lat},{lng}););out center tags;')
    return get_json(OVERPASS, {"data": q})["elements"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("city", help="city slug from data/cities.csv")
    parser.add_argument("--radius", type=float, default=5.0, help="search radius in km (default 5)")
    args = parser.parse_args()
    lat, lng = city_centre(args.city)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["name", "kind", "lat", "lng", "cuisine", "vegetarian", "opening_hours", "osm"])
    rows = []
    for e in query(lat, lng, args.radius):
        tags = e.get("tags", {})
        kind = KINDS.get(tags.get("amenity") or tags.get("shop"), "food")
        point = (e.get("lat"), e.get("lon")) if "lat" in e else (e["center"]["lat"], e["center"]["lon"])
        veg = "yes" if tags.get("diet:vegetarian") in ("only", "yes") else ""
        rows.append([tags["name"], kind, round(point[0], 5), round(point[1], 5), tags.get("cuisine", ""), veg,
                     tags.get("opening_hours", ""), f"{e['type']}/{e['id']}"])
    for row in sorted(rows):
        writer.writerow(row)
    print(f"{len(rows)} named places (© OpenStreetMap contributors, ODbL)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
