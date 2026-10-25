"""One-off data script: five stay areas per city (North, South, East, West, Central).

    python scripts/build_stay_areas.py fetch      # OpenStreetMap (Overpass) -> instance/osm_cache/stays/<city>.json
    python scripts/build_stay_areas.py geocode    # curated names (data/curation/stay_candidates.csv) -> Nominatim
    python scripts/build_stay_areas.py build      # choose the areas -> data/stay_areas.csv + a review report
    python scripts/build_stay_areas.py report     # print the chosen areas, flagged ones first
    python scripts/build_stay_areas.py candidates delhi   # the top candidates per sector, for review

A stay area is a named neighbourhood, suburb, town or village from
OpenStreetMap (place=suburb/quarter/neighbourhood/town/village/hamlet) --
never an attraction, a railway station or an airport. For each city:

    1. candidates = named OSM places around the city centre (radius from how far
       the city's attractions spread; wider for small towns with few places)
    2. accommodation = OSM tourism=hotel/guest_house/hostel/motel/apartment
    3. score(candidate) = 3 x log2(1 + places to stay within 1 km)
                          + a small bonus for larger place types and a Wikidata link
                          - 0.5 per km beyond where most of the city's sights are
       (so an area people actually stay in beats an empty locality, and a nearby
       area beats a far-off village); an area with nowhere to stay is used only
       if its sector has no area with accommodation at all
    4. Central = best candidate near the centre; North/East/South/West = best
       candidate in that 90-degree compass sector, far enough out to differ
       from Central, no two within 600 m of each other.
    5. If a sector has no candidate (sea, mountains, a valley town), the closest
       remaining area by bearing is used and the row gets a direction_note that
       says where it really is ("The sea lies south of ... this area is
       north-east of the centre"). Nothing is moved and no coordinate is invented.

Candidates come from two OpenStreetMap routes: the named places Overpass finds
around the centre, and a reviewed list of well-known accommodation localities
(data/curation/stay_candidates.csv) located with Nominatim. The list only says
which names to consider -- coordinates, ids, the places-to-stay count and the
direction always come from OpenStreetMap, and a listed name gets a bonus
(+6) so a known stay area beats an anonymous locality in the same sector.
Every chosen area must be within 1 km of a drivable road (OSRM "nearest"), so a
trek-only village is never a stay area. data/curation/stay_overrides.csv can
force a candidate (by name) into a slot. Every row keeps its OSM id and URL.

Data (c) OpenStreetMap contributors, ODbL.
"""

import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse

from net import fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(ROOT, "instance", "osm_cache", "stays")
OUT = os.path.join(DATA, "stay_areas.csv")
OVERRIDES = os.path.join(DATA, "curation", "stay_overrides.csv")
REPORT = os.path.join(DATA, "curation", "stay_review.csv")
OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM_NEAREST = "https://router.project-osrm.org/nearest/v1/driving/"
CURATED = os.path.join(DATA, "curation", "stay_candidates.csv")
GEOCODE_CACHE = os.path.join(ROOT, "instance", "osm_cache", "nominatim_stays.json")
SNAP_CACHE = os.path.join(ROOT, "instance", "osm_cache", "stay_snaps.json")
CURATED_BONUS = 6
MAX_ROAD_SNAP_M = 1000
GEOCODE_TYPES = {"suburb", "neighbourhood", "quarter", "village", "town", "hamlet", "city_district", "locality",
                 "administrative", "city", "borough", "residential"}

PLACE_TYPES = {"suburb": 2, "quarter": 2, "town": 2, "neighbourhood": 1, "village": 0, "hamlet": -1}
NEARBY_KM = 1.0              # accommodation counted within this distance of an area
MIN_GAP_KM = 1.5             # two chosen areas are at least this far apart (distinct parts of the city)
SECTORS = [("north", 0), ("east", 90), ("south", 180), ("west", 270)]
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
NOT_A_STAY = re.compile(r"station|railway|junction|airport|terminal|bus stand|bus stop|depot|cantonment board|"
                        r"\bfort\b|\btemple\b|\bmandir\b|\bmasjid\b|\bchurch\b|\bghat\b|\blake\b|\bbeach\b|"
                        r"\bpark\b|\bmuseum\b|\bpalace\b", re.I)
FIELDS = ["city", "slug", "name", "direction", "lat", "lng", "coord_source", "osm_type", "osm_id", "osm_place",
          "hotels_nearby", "distance_km", "bearing", "direction_note", "source_url"]


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(h))


def bearing(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_gap(a, b):
    return abs((a - b + 180) % 360 - 180)


def compass(deg):
    return COMPASS[int((deg + 22.5) // 45) % 8]


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def latin(text):
    return bool(text) and all(ord(ch) < 0x250 for ch in text)


def city_rows():
    return read_csv(os.path.join(DATA, "cities.csv"))


def attraction_rows():
    return read_csv(os.path.join(DATA, "attractions.csv"))


def search_radius_km(city, attractions):
    """How far out to look: wide enough to cover where the city's sights are."""
    spread = sorted(haversine_km(city["lat"], city["lng"], float(a["lat"]), float(a["lng"])) for a in attractions)
    p80 = spread[int(0.8 * (len(spread) - 1))] if spread else 3.0
    return max(4.0, min(15.0, 1.3 * p80))


# ----------------------------------------------------------------------------- fetch

def overpass(lat, lng, radius_km):
    r = int(radius_km * 1000)
    query = (f'[out:json][timeout:120];('
             f'node(around:{r},{lat},{lng})[place~"^(suburb|quarter|neighbourhood|town|village|hamlet)$"][name];'
             f'nw(around:{r},{lat},{lng})[tourism~"^(hotel|guest_house|hostel|motel|apartment)$"];'
             f');out tags center qt;')
    for attempt in range(6):                      # the public server answers 502/504 when busy
        try:
            return json.loads(fetch(f"{OVERPASS}?data={urllib.parse.quote(query)}", timeout=180))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 5:
                raise
            print(f"  overpass busy ({exc}), retrying", flush=True)
            time.sleep(20 * (attempt + 1))


def fetch_all(only=None):
    os.makedirs(CACHE, exist_ok=True)
    by_city = {}
    for a in attraction_rows():
        by_city.setdefault(a["city"], []).append(a)
    rows = city_rows()
    if only and "--reverse" in only:                # a second worker can work from the other end of the list
        rows, only = rows[::-1], None
    for row in rows:
        slug = row["slug"]
        if only and slug not in only:
            continue
        path = os.path.join(CACHE, f"{slug}.json")
        if os.path.exists(path):
            continue
        city = {"lat": float(row["center_lat"]), "lng": float(row["center_lng"])}
        radius = search_radius_km(city, by_city.get(slug, []))
        try:
            data = overpass(city["lat"], city["lng"], radius)
        except Exception as exc:                  # keep going; a re-run fetches only what is missing
            print(f"{slug}: FAILED ({exc})", flush=True)
            continue
        places = [e for e in data["elements"] if "place" in e.get("tags", {})]
        if len(places) < 12:                     # small or remote town: look further out
            radius = max(radius * 2.5, 25.0)
            time.sleep(5)
            data = overpass(city["lat"], city["lng"], radius)
        data["radius_km"] = radius
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        n_places = sum(1 for e in data["elements"] if "place" in e.get("tags", {}))
        print(f"{slug}: radius {radius:.1f} km, {n_places} named places, "
              f"{len(data['elements']) - n_places} places to stay", flush=True)
        time.sleep(5)


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=0, sort_keys=True)


def geocode_all():
    """Locate every curated name with Nominatim (1 request per second, cached)."""
    from net import get_json
    cache = load_json(GEOCODE_CACHE)
    cities = {r["slug"]: r for r in city_rows()}
    for row in read_csv(CURATED):
        key = f"{row['city']}|{row['name']}"
        if key in cache and any(is_place(h) for h in cache[key]):
            continue
        c = cities[row["city"]]
        city_name, state = c["name"].split(" (")[0], c["state"].split(" (")[0]
        hits = []
        for query in (f"{row['name']}, {city_name}, {state}, India", f"{row['name']}, {city_name}, India",
                      f"{row['name']}, {state}, India"):
            try:
                found = get_json(NOMINATIM, {"q": query, "format": "json", "limit": 5, "countrycodes": "in"})
            except Exception as exc:
                print(f"{key}: FAILED ({exc})", flush=True)
                found = []
            time.sleep(1.1)
            hits += found
            if any(is_place(h) for h in found):
                break
        cache[key] = hits
        save_json(GEOCODE_CACHE, cache)
        print(f"{key}: {'place found' if any(is_place(h) for h in hits) else 'no place'}", flush=True)


def is_place(hit):
    return hit.get("class") in ("place", "boundary", "landuse") and hit.get("type") in GEOCODE_TYPES


def curated_candidates(slug, city, stays_nearby, limit_km, counted_km):
    """Curated names that Nominatim placed as an OSM place within limit_km of the centre."""
    cache = load_json(GEOCODE_CACHE)
    out = []
    for row in read_csv(CURATED):
        if row["city"] != slug:
            continue
        wanted = re.sub(r"[^a-z0-9]", "", row["name"].lower())
        for hit in cache.get(f"{slug}|{row['name']}", []):
            if not is_place(hit):
                continue
            own = re.sub(r"[^a-z0-9]", "", hit.get("display_name", "").split(",")[0].lower())
            if wanted not in own and own not in wanted:
                continue                                   # Nominatim matched a different place
            lat, lng = float(hit["lat"]), float(hit["lon"])
            dist = haversine_km(city["lat"], city["lng"], lat, lng)
            if dist > limit_km:
                continue
            out.append({"name": row["name"], "lat": lat, "lng": lng, "osm_type": hit["osm_type"],
                        "osm_id": hit["osm_id"], "osm_place": hit["type"], "dist": dist,
                        "bearing": bearing(city["lat"], city["lng"], lat, lng), "curated": True,
                        # Places to stay were fetched only within counted_km of the centre: beyond it the count is unknown.
                        "hotels": (sum(1 for p in stays_nearby if haversine_km(lat, lng, p[0], p[1]) <= NEARBY_KM)
                                   if dist <= counted_km - NEARBY_KM else None)})
            break                                          # Nominatim's best place match only
    return out


def road_snap_m(c):
    """Metres from the area's point to the nearest drivable road (OSRM), cached."""
    from net import get_json
    cache = load_json(SNAP_CACHE)
    key = f"{c['lat']:.6f},{c['lng']:.6f}"
    if key not in cache:
        data = get_json(f"{OSRM_NEAREST}{c['lng']:.6f},{c['lat']:.6f}")
        cache[key] = round(data["waypoints"][0]["distance"]) if data.get("code") == "Ok" else None
        save_json(SNAP_CACHE, cache)
        time.sleep(0.3)
    return cache[key]


# ----------------------------------------------------------------------------- build

def point(e):
    if "lat" in e:
        return e["lat"], e["lon"]
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)


def clean_name(name):
    """'Barodia Scheme , Jaipur' -> 'Barodia Scheme' (OSM names sometimes carry the city)."""
    return re.sub(r"\s+", " ", name.split(",")[0]).strip()


def candidates_for(slug, city, attractions):
    path = os.path.join(CACHE, f"{slug}.json")
    data = load_json(path) or {"elements": [], "radius_km": search_radius_km(city, attractions)}
    spread = sorted(haversine_km(city["lat"], city["lng"], float(a["lat"]), float(a["lng"])) for a in attractions)
    near = max(2.0, spread[len(spread) // 2] if spread else 3.0)     # half the sights lie within this
    stays = [point(e) for e in data["elements"] if "tourism" in e.get("tags", {})]
    stays = [p for p in stays if p[0] is not None]
    blocked = {re.sub(r"\W+", " ", a["name"].lower()).strip() for a in attractions}
    # Another destination of the dataset (Pushkar for Ajmer, Vrindavan for Mathura) is not a part of this city.
    blocked |= {re.sub(r"\W+", " ", c["name"].split(" (")[0].lower()).strip() for c in city_rows() if c["slug"] != slug}
    blocked |= {re.sub(r"\W+", " ", r["osm_name"].lower()).strip() for r in read_csv(OVERRIDES)
                if r["city"] == slug and r["direction"] == "reject"}
    out, seen = [], set()
    for e in data["elements"]:
        tags = e.get("tags", {})
        if "place" not in tags or tags.get("place") not in PLACE_TYPES:
            continue
        name = tags.get("name:en") if latin(tags.get("name:en")) else tags.get("name")
        if not latin(name) or NOT_A_STAY.search(name):
            continue
        name = clean_name(name)
        key = re.sub(r"\W+", " ", name.lower()).strip()
        if key in blocked or key in seen:
            continue                              # an attraction's own name, or a duplicate name
        seen.add(key)
        lat, lng = e["lat"], e["lon"]
        hotels = sum(1 for p in stays if haversine_km(lat, lng, p[0], p[1]) <= NEARBY_KM)
        dist = haversine_km(city["lat"], city["lng"], lat, lng)
        out.append({
            "name": name, "lat": lat, "lng": lng, "osm_type": "node", "osm_id": e["id"],
            "osm_place": tags["place"], "hotels": hotels,
            "score": round(3 * math.log2(1 + hotels) + PLACE_TYPES[tags["place"]] + (1 if tags.get("wikidata") else 0)
                           - 0.5 * max(0.0, dist - near), 2),
            "dist": dist,
            "bearing": bearing(city["lat"], city["lng"], lat, lng),
        })
    limit = min(60.0, max(20.0, 2.5 * data["radius_km"]))
    curated = curated_candidates(slug, city, stays, limit, data["radius_km"])
    for c in curated:
        c["score"] = round(3 * math.log2(1 + (c["hotels"] or 0)) + CURATED_BONUS - 0.5 * max(0.0, c["dist"] - near), 2)
    names = {c["name"].lower() for c in curated}
    out = curated + [c for c in out if c["name"].lower() not in names and c["name"].lower() not in blocked]
    out = [c for c in out if re.sub(r"\W+", " ", c["name"].lower()).strip() not in blocked]
    return out, data["radius_km"]


def choose(slug, city, cands, radius, overrides, check_road=True):
    chosen = {}

    def reachable(c):
        """Within MAX_ROAD_SNAP_M of a drivable road (looked up only for areas about to be chosen)."""
        if not check_road:
            return True
        if "snap_m" not in c:
            c["snap_m"] = road_snap_m(c)
        return c["snap_m"] is not None and c["snap_m"] <= MAX_ROAD_SNAP_M

    def free(c):
        return all(haversine_km(c["lat"], c["lng"], o["lat"], o["lng"]) >= MIN_GAP_KM for o in chosen.values())

    def best(pool):
        """Highest score that a road reaches; an area with somewhere to stay always beats one without."""
        ranked = sorted(pool, key=lambda c: (has_hotels(c) or c.get("curated", False), c["score"], -c["dist"], c["name"]),
                        reverse=True)
        return next((c for c in ranked if reachable(c)), None)

    def has_hotels(c):
        return bool(c["hotels"])

    by_name = {c["name"].lower(): c for c in cands}
    for direction, name in overrides.get(slug, {}).items():
        c = by_name.get(name.lower())
        if c is None:
            raise SystemExit(f"{slug}: override '{name}' for {direction} is not an OSM candidate")
        chosen[direction] = dict(c, note="")

    if "central" not in chosen:
        inner = max(2.5, 0.3 * radius)
        pool = [c for c in cands if c["dist"] <= inner and free(c)]
        pick = best(pool) or min((c for c in cands if free(c) and reachable(c)), key=lambda c: c["dist"], default=None)
        if pick:
            note = "" if pick["dist"] <= inner else (f"Nearest named area to the centre "
                                                     f"({pick['dist']:.1f} km {compass(pick['bearing'])}).")
            chosen["central"] = dict(pick, note=note)
    centre_gap = max(1.0, 0.15 * radius)
    for direction, deg in SECTORS:
        if direction in chosen:
            continue
        taken = {id(c) for c in chosen.values()}
        usable = [c for c in cands if c["dist"] >= centre_gap and free(c) and id(c) not in taken]
        far = max(8.0, 0.6 * radius)            # an area far beyond the city is not "its" north / south ...
        pick = best([c for c in usable if angle_gap(c["bearing"], deg) <= 45 and c["dist"] <= far]) or \
            best([c for c in usable if angle_gap(c["bearing"], deg) <= 45])
        note = ""
        if pick is None:
            pick = best([c for c in usable if angle_gap(c["bearing"], deg) <= 67.5])
            if pick is None:
                pool = [c for c in cands if free(c) and id(c) not in taken]
                pick = min((c for c in pool if reachable(c)), key=lambda c: (angle_gap(c["bearing"], deg), -c["score"]),
                           default=None)
            if pick is not None:
                note = (f"No named area lies {direction} of the centre in OpenStreetMap; this is the closest "
                        f"by direction and is actually {pick['dist']:.1f} km {compass(pick['bearing'])} of the centre.")
        if pick is not None:
            chosen[direction] = dict(pick, note=note)
    return chosen


def build():
    overrides = {}
    for row in read_csv(OVERRIDES):
        if row["direction"] != "reject":
            overrides.setdefault(row["city"], {})[row["direction"]] = row["osm_name"]
    by_city = {}
    for a in attraction_rows():
        by_city.setdefault(a["city"], []).append(a)
    rows, problems, used_slugs = [], [], set()
    for row in city_rows():
        slug = row["slug"]
        city = {"lat": float(row["center_lat"]), "lng": float(row["center_lng"])}
        if not os.path.exists(os.path.join(CACHE, f"{slug}.json")):
            problems.append(f"{slug}: Overpass data not fetched (curated names only, no places-to-stay counts)")
        cands, radius = candidates_for(slug, city, by_city.get(slug, []))
        chosen = choose(slug, city, cands, radius, overrides)
        for direction in ["central", "north", "east", "south", "west"]:
            c = chosen.get(direction)
            if c is None:
                problems.append(f"{slug}: no OpenStreetMap area for {direction}")
                continue
            note = c["note"]
            if c["hotels"] is None:
                note = (note + " " if note else "") + "Outside the area searched for places to stay, so they were not counted."
            elif c["hotels"] == 0:
                note = (note + " " if note else "") + ("OpenStreetMap lists no hotel or guest house within 1 km of "
                                                      "this point; check that you can stay here.")
            stay_slug = f"{slug}-stay-{direction}"
            assert stay_slug not in used_slugs
            used_slugs.add(stay_slug)
            rows.append({
                "city": slug, "slug": stay_slug, "name": c["name"], "direction": direction,
                "lat": f"{c['lat']:.6f}", "lng": f"{c['lng']:.6f}", "coord_source": "openstreetmap",
                "osm_type": c["osm_type"], "osm_id": c["osm_id"], "osm_place": c["osm_place"],
                "hotels_nearby": "" if c["hotels"] is None else c["hotels"], "distance_km": f"{c['dist']:.2f}", "bearing": f"{c['bearing']:.0f}",
                "direction_note": note,
                "source_url": f"https://www.openstreetmap.org/{c['osm_type']}/{c['osm_id']}",
            })
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    # Review file: every chosen area, then every curated name OpenStreetMap could not place (kept for a later retry).
    cache = load_json(GEOCODE_CACHE)
    unplaced = [r for r in read_csv(CURATED) if not any(is_place(h) for h in cache.get(f"{r['city']}|{r['name']}", []))]
    with open(REPORT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["city", "status", "direction", "name", "hotels_nearby", "distance_km", "note"])
        for r in rows:
            writer.writerow([r["city"], "chosen", r["direction"], r["name"], r["hotels_nearby"], r["distance_km"],
                             r["direction_note"]])
        for r in unplaced:
            writer.writerow([r["city"], "curated name not found as an OSM place", "", r["name"], "", "", ""])
    print(f"wrote {len(rows)} stay areas to {os.path.relpath(OUT, ROOT)}; "
          f"{len(unplaced)} curated names not found in OSM are listed in {os.path.relpath(REPORT, ROOT)}")
    for p in problems:
        print("PROBLEM", p)
    return rows, problems


def report():
    rows = read_csv(OUT)
    flagged = [r for r in rows if r["direction_note"] or r["hotels_nearby"] in ("", "0")]
    for r in flagged + [r for r in rows if r not in flagged]:
        print(f"{r['city']:12} {r['direction']:8} {r['name'][:32]:32} {r['osm_place']:13} hotels {r['hotels_nearby']:>4} "
              f"{r['distance_km']:>6} km {r['bearing']:>4}°  {r['direction_note'][:70]}")


def show_candidates(only=None):
    """Top OpenStreetMap candidates per sector, to review the automatic choice (and write overrides)."""
    by_city = {}
    for a in attraction_rows():
        by_city.setdefault(a["city"], []).append(a)
    for row in city_rows():
        slug = row["slug"]
        if (only and slug not in only) or not os.path.exists(os.path.join(CACHE, f"{slug}.json")):
            continue
        city = {"lat": float(row["center_lat"]), "lng": float(row["center_lng"])}
        cands, radius = candidates_for(slug, city, by_city.get(slug, []))
        print(f"== {slug} (radius {radius:.0f} km)")
        inner = max(1.0, 0.15 * radius)
        sectors = [("central", None)] + SECTORS
        for direction, deg in sectors:
            if deg is None:
                pool = [c for c in cands if c["dist"] <= max(inner, 2.5)]
            else:
                pool = [c for c in cands if angle_gap(c["bearing"], deg) <= 45 and c["dist"] >= 1.0]
            top = sorted(pool, key=lambda c: (-((c["hotels"] or 0) > 0), -c["score"]))[:7]
            print(f"  {direction:7}: " + "; ".join(f"{c['name']} [{c['osm_place'][:5]} h{c['hotels']} {c['dist']:.1f}km]"
                                               for c in top))


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "build"
    if stage == "fetch":
        fetch_all(set(sys.argv[2:]) or None)
    elif stage == "geocode":
        geocode_all()
    elif stage == "build":
        build()
    elif stage == "report":
        report()
    elif stage == "candidates":
        show_candidates(set(sys.argv[2:]) or None)
    else:
        raise SystemExit(__doc__)
