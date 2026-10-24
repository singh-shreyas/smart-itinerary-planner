"""One-off data script: build the 46 newer cities from open data (run by hand, needs internet).

    python scripts/build_city_dataset.py fetch    # query the sources -> data/curation/source_snapshot.json
    python scripts/build_city_dataset.py build    # snapshot + curation -> data/*.csv rows for those cities
    python scripts/build_city_dataset.py report   # print what needs a human look (coordinate disagreements, ...)
    python scripts/build_city_dataset.py images   # free-licence photos + data/image_credits.csv

Inputs (both reviewed by a person):
    data/catalog/top50.csv               the team's Top-50 destination list (city + famous attractions)
    data/curation/attraction_titles.csv  each catalog name -> Wikipedia article / OSM search / skip, with
                                         its kind of place, interests and any access restriction
    data/curation/cities.csv             city taglines, descriptions and start points (railway station etc.)

Sources, and what each one is trusted for:
    Wikipedia (CC BY-SA)       coordinates, a two-sentence description, the free-licence lead photo
    Wikidata (CC0)             coordinates when Wikipedia has none; a cross-check when it does
    Wikimedia page views       12 months of views -> the popularity value (log scale, fixed bounds)
    OpenStreetMap (ODbL)       coordinates when there is no article (Nominatim, max 1 request/second);
                               opening_hours and fee tags when mapped (via Nominatim extratags / Overpass)

What is NOT available from any open source and is therefore never invented:
    visitor ratings            -> left empty ("not rated"); the planner uses a neutral prior
    hours / fees / visit times -> taken from OSM when tagged, otherwise the documented default for
                                  that kind of place (data/estimate_defaults.csv), marked "estimate"

The four original cities (Delhi, Agra, Jaipur, Varanasi) are left exactly as they are.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.parse
from datetime import date, timedelta

from net import get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CURATION = os.path.join(DATA, "curation")
SNAPSHOT = os.path.join(CURATION, "source_snapshot.json")
ORIGINAL_CITIES = {"delhi", "agra", "jaipur", "varanasi"}
ORIGINAL_CENTRES = {"delhi": {"lat": 28.6139, "lng": 77.2090, "title": "Delhi"},
                    "agra": {"lat": 27.1767, "lng": 78.0081, "title": "Agra"},
                    "jaipur": {"lat": 26.9124, "lng": 75.7873, "title": "Jaipur"},
                    "varanasi": {"lat": 25.3176, "lng": 82.9739, "title": "Varanasi"}}
WIKI = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{}/monthly/{}/{}"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Popularity = position of log10(annual page views) between two FIXED bounds, so adding data
# never changes the popularity of places already in the dataset:
#   1,000 views a year -> 0.0      3,000,000 views a year -> 1.0
VIEWS_LOW, VIEWS_HIGH = 1_000, 3_000_000
POPULARITY_NO_ARTICLE = 0.3          # catalog sights without an article: a modest, labelled default
COORD_DISAGREE_KM = 2.0              # Wikipedia vs Wikidata/OSM further apart than this -> human review


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r[next(iter(r))] and not r[next(iter(r))].startswith("#")]


def slugify(text):
    text = text.lower().replace("&", "and")
    text = re.sub(r"[’'`().,]", "", text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def food_rows():
    """data/curation/food_shopping.csv in the same shape as attraction_titles.csv rows (status 'extra')."""
    path = os.path.join(CURATION, "food_shopping.csv")
    if not os.path.exists(path):
        return []
    rows = []
    for r in read_rows(path):
        rows.append({"city": r["city"], "catalog_name": "", "name": r["name"], "wiki_title": r["wiki_title"],
                     "osm_query": "", "place_type": r["place_type"], "status": "extra", "access": "", "access_note": "",
                     "categories": r["categories"], "cuisine": r.get("cuisine", ""),
                     "vegetarian": r.get("vegetarian") or "unknown"})
    return rows


# --------------------------------------------------------------------------- fetch

def wiki_query(titles, props):
    """Resolve redirects and return {requested title: page dict}."""
    out = {}
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        params = {"action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                  "titles": "|".join(chunk), "prop": props, "colimit": "max"}
        if "extracts" in props:
            params.update(exintro=1, explaintext=1, exsentences=2, exlimit="max")
        if "pageimages" in props:
            params.update(piprop="name", pilicense="free", pilimit="max")
        data = get_json(WIKI, params)
        query = data["query"]
        rename = {s["from"]: s["to"] for s in query.get("normalized", []) + query.get("redirects", [])}
        pages = {p["title"]: p for p in query["pages"]}
        for title in chunk:
            final = title
            while final in rename:
                final = rename[final]
            out[title] = pages.get(final, {})
        time.sleep(0.3)
    return out


def wikidata_coords(qids):
    out = {}
    qids = [q for q in qids if q]
    for i in range(0, len(qids), 50):
        data = get_json(WIKIDATA, {"action": "wbgetentities", "format": "json", "ids": "|".join(qids[i:i + 50]),
                                   "props": "claims"})
        for qid, entity in data.get("entities", {}).items():
            claims = entity.get("claims", {}).get("P625", [])
            if claims:
                value = claims[0]["mainsnak"].get("datavalue", {}).get("value")
                if value:
                    out[qid] = [value["latitude"], value["longitude"]]
        time.sleep(0.3)
    return out


def nominatim(query, near):
    """First OSM result within 60 km of `near` ([lat, lng]), with its tags. Respects 1 request/second."""
    time.sleep(1.1)
    results = get_json(NOMINATIM, {"q": query, "format": "jsonv2", "limit": 5, "extratags": 1, "countrycodes": "in"})
    for r in results:
        lat, lng = float(r["lat"]), float(r["lon"])
        if haversine_km(near[0], near[1], lat, lng) <= 60:
            return {"lat": lat, "lng": lng, "name": r.get("name") or r.get("display_name", "").split(",")[0],
                    "osm": f"{r.get('osm_type')}/{r.get('osm_id')}", "category": f"{r.get('category')}:{r.get('type')}",
                    "tags": r.get("extratags") or {}}
    return None


def pageviews(title):
    end = date.today().replace(day=1) - timedelta(days=1)          # last day of last month
    start = (end.replace(day=1) - timedelta(days=330)).replace(day=1)
    url = PAGEVIEWS.format(urllib.parse.quote(title.replace(" ", "_"), safe=""), start.strftime("%Y%m01"),
                           end.strftime("%Y%m%d"))
    try:
        data = get_json(url)
    except Exception:                                              # 404 = no views recorded
        return None
    return sum(item["views"] for item in data.get("items", []))


def overpass_tags(qids, centre, radius_km):
    """OSM tags of objects carrying one of these Wikidata ids, near the city."""
    query = (f'[out:json][timeout:60];nwr["wikidata"](around:{int(radius_km * 1000)},{centre[0]},{centre[1]});'
             f'out tags center;')
    try:
        data = get_json(OVERPASS, {"data": query})
    except Exception as exc:
        print(f"  overpass failed ({exc})")
        return {}
    found = {}
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        if tags.get("wikidata") in qids and tags["wikidata"] not in found:
            found[tags["wikidata"]] = tags
    return found


def fetch():
    curation = read_rows(os.path.join(CURATION, "attraction_titles.csv"))
    cities_cur = {r["slug"]: r for r in read_rows(os.path.join(CURATION, "cities.csv"))}
    snapshot = {"fetched": date.today().isoformat(), "cities": {}, "attractions": {}, "starts": {}}
    if os.path.exists(SNAPSHOT):
        with open(SNAPSHOT, encoding="utf-8") as f:
            snapshot.update(json.load(f))

    print("cities ...")
    city_pages = wiki_query([c["wiki_title"] for c in cities_cur.values()], "coordinates|pageprops|pageimages")
    for slug, c in cities_cur.items():
        page = city_pages.get(c["wiki_title"], {})
        co = (page.get("coordinates") or [{}])[0]
        snapshot["cities"][slug] = {"title": page.get("title"), "lat": co.get("lat"), "lng": co.get("lon"),
                                    "qid": page.get("pageprops", {}).get("wikibase_item"),
                                    "image": page.get("pageimage")}

    rows = [r for r in curation if r["status"] in ("map", "extra", "osm")] + food_rows()
    titles = sorted({r["wiki_title"] for r in rows if r["wiki_title"]})
    print(f"{len(titles)} articles ...")
    pages = wiki_query(titles, "coordinates|pageprops|description|extracts|pageimages")
    qids = {t: p.get("pageprops", {}).get("wikibase_item") for t, p in pages.items()}
    wd = wikidata_coords(sorted(set(q for q in qids.values() if q)))

    for r in rows:
        key = f"{r['city']}|{r['name']}"
        old = snapshot["attractions"].get(key, {})
        city = snapshot["cities"].get(r["city"]) or ORIGINAL_CENTRES[r["city"]]
        centre = [city["lat"], city["lng"]]
        entry = {"city": r["city"], "name": r["name"], "status": r["status"]}
        if r["wiki_title"]:
            page = pages.get(r["wiki_title"], {})
            co = (page.get("coordinates") or [{}])[0]
            entry.update(title=page.get("title"), qid=qids.get(r["wiki_title"]), extract=page.get("extract", ""),
                         description=page.get("description", ""), image=page.get("pageimage"),
                         wiki_coords=[co["lat"], co["lon"]] if co else None,
                         wikidata_coords=wd.get(qids.get(r["wiki_title"])))
            entry["views"] = old["views"] if old.get("views") else pageviews(page.get("title") or r["wiki_title"])
            time.sleep(0.05)
        need_osm = r["status"] == "osm" or (r["osm_query"] and not entry.get("wiki_coords"))
        if need_osm or (entry.get("wiki_coords") and entry.get("wikidata_coords") and
                        haversine_km(*entry["wiki_coords"], *entry["wikidata_coords"]) > COORD_DISAGREE_KM):
            query = r["osm_query"] or f"{r['name']}, {city['title']}"
            entry["osm"] = old.get("osm") if old.get("osm_query") == query else nominatim(query, centre)
            entry["osm_query"] = query
        snapshot["attractions"][key] = entry
        print(f"  {key:50} wiki={bool(entry.get('wiki_coords'))} wd={bool(entry.get('wikidata_coords'))} "
              f"osm={bool(entry.get('osm'))} views={entry.get('views')}")

    print("start points ...")
    for slug, c in cities_cur.items():
        for i, spec in enumerate(filter(None, c["starts"].split("|"))):
            label, _, source = spec.partition("=")
            key = f"{slug}|{label}"
            if key in snapshot["starts"]:
                continue
            centre = [snapshot["cities"][slug]["lat"], snapshot["cities"][slug]["lng"]]
            kind, _, value = source.partition(":")
            if kind == "wiki":
                page = wiki_query([value], "coordinates").get(value, {})
                co = (page.get("coordinates") or [{}])[0]
                snapshot["starts"][key] = {"lat": co.get("lat"), "lng": co.get("lon"), "source": "wikipedia",
                                           "title": page.get("title")}
            elif kind == "osm":
                hit = nominatim(value, centre)
                snapshot["starts"][key] = {"lat": hit and hit["lat"], "lng": hit and hit["lng"],
                                           "source": "openstreetmap", "osm": hit and hit["osm"]}
            elif kind == "centre":
                snapshot["starts"][key] = {"lat": centre[0], "lng": centre[1], "source": "wikipedia",
                                           "title": snapshot["cities"][slug]["title"]}

    print("OpenStreetMap tags (Overpass) ...")
    by_city = {}
    for key, e in snapshot["attractions"].items():
        if e.get("qid"):
            by_city.setdefault(e["city"], []).append(e)
    for slug, entries in sorted(by_city.items()):
        if all("osm_tags" in e for e in entries):
            continue
        city = snapshot["cities"].get(slug) or ORIGINAL_CENTRES[slug]
        far = max(haversine_km(city["lat"], city["lng"], *(e.get("wiki_coords") or e.get("wikidata_coords")
                                                           or [city["lat"], city["lng"]])) for e in entries)
        tags = overpass_tags({e["qid"] for e in entries}, [city["lat"], city["lng"]], far + 3)
        for e in entries:
            e["osm_tags"] = tags.get(e["qid"], {})
        print(f"  {slug:12} {sum(1 for e in entries if e['osm_tags'])}/{len(entries)} found in OSM")
        time.sleep(2)

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"wrote {SNAPSHOT}")


# --------------------------------------------------------------------------- choose values

def choose_coords(entry):
    """(lat, lng, source). Fixed priority: Wikipedia, then Wikidata, then OpenStreetMap.

    Where the sources disagree by more than 2 km, `report` lists the place and a
    person records the correct choice in data/curation/coordinate_review.csv
    (use = wikipedia / wikidata / osm / manual); that choice always wins here.
    """
    wiki, wd, osm = entry.get("wiki_coords"), entry.get("wikidata_coords"), entry.get("osm")
    sources = {"wikipedia": wiki, "wikidata": wd, "osm": [osm["lat"], osm["lng"]] if osm else None}
    choice = entry.get("coord_choice")
    if choice in sources and sources[choice]:
        lat, lng = sources[choice]
        return lat, lng, "openstreetmap" if choice == "osm" else choice
    for name in ("wikipedia", "wikidata", "osm"):
        if sources[name]:
            lat, lng = sources[name]
            return lat, lng, "openstreetmap" if name == "osm" else name
    return None


def popularity(views):
    if not views:
        return None
    value = (math.log10(views) - math.log10(VIEWS_LOW)) / (math.log10(VIEWS_HIGH) - math.log10(VIEWS_LOW))
    return round(min(1.0, max(0.05, value)), 2)


DAY_NAMES = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}


def parse_osm_hours(text):
    """A small, strict reader for common OpenStreetMap opening_hours values.

    Accepts '24/7', 'HH:MM-HH:MM[,HH:MM-HH:MM]', and rules like 'Mo-Su 09:00-17:00; Fr off'.
    Anything else (sunrise, public holidays, months, ...) returns None and the default is used.
    Returns {weekday: [(open, close), ...]}.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    result = {}
    for rule in [r.strip() for r in text.split(";") if r.strip()]:
        m = re.fullmatch(r"(?:([A-Z][a-z](?:-[A-Z][a-z])?(?:,[A-Z][a-z](?:-[A-Z][a-z])?)*)\s+)?(off|closed|[\d:,\-\s]+)", rule)
        if not m:
            return None
        days_spec, times = m.group(1), m.group(2).strip()
        days = set()
        for part in (days_spec or "Mo-Su").split(","):
            if "-" in part:
                a, b = (DAY_NAMES.get(x) for x in part.split("-"))
                if a is None or b is None:
                    return None
                d = a
                while True:
                    days.add(d)
                    if d == b:
                        break
                    d = (d + 1) % 7
            else:
                if part not in DAY_NAMES:
                    return None
                days.add(DAY_NAMES[part])
        if times in ("off", "closed"):
            for d in days:
                result[d] = []
            continue
        windows = []
        for span in times.split(","):
            tm = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", span)
            if not tm:
                return None
            o = int(tm.group(1)) * 60 + int(tm.group(2))
            c = int(tm.group(3)) * 60 + int(tm.group(4))
            if c <= o or c > 1440:
                return None                                      # past midnight: not supported
            windows.append((o, c))
        for d in days:
            result[d] = sorted(windows)
    return result


def parse_osm_fee(tags):
    """(fee_inr or None, note). Only 'fee=no' and a single plain INR amount are accepted."""
    fee, charge = (tags.get("fee") or "").lower(), tags.get("charge") or ""
    if fee == "no":
        return 0, "osm fee=no"
    m = re.fullmatch(r"\s*(?:INR|₹|Rs\.?)\s*(\d+)\s*|\s*(\d+)\s*(?:INR|₹)\s*", charge)
    if m:
        return int(m.group(1) or m.group(2)), "osm charge"
    return None, ""


def fmt(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# --------------------------------------------------------------------------- build

ATTRACTION_FIELDS = ["city", "slug", "name", "lat", "lng", "coord_source", "categories", "rating", "rating_source",
                     "popularity", "popularity_source", "pageviews_12m", "visit_minutes", "duration_source",
                     "fee_inr", "fee_source", "hours_source", "in_team_catalog", "data_status", "wiki_title",
                     "wikidata", "place_type", "access", "access_note", "cuisine", "vegetarian", "description_source",
                     "description"]


ORIGINAL_SLUGS_CACHE = set()


def build():
    ORIGINAL_SLUGS_CACHE.clear()
    ORIGINAL_SLUGS_CACHE.update(original_slugs())
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)
    curation = read_rows(os.path.join(CURATION, "attraction_titles.csv"))
    cities_cur = read_rows(os.path.join(CURATION, "cities.csv"))
    top50 = {r["destination"]: r for r in read_rows(os.path.join(DATA, "catalog", "top50.csv"))}
    defaults = {r["place_type"]: r for r in read_rows(os.path.join(DATA, "estimate_defaults.csv"))}
    overrides = {}
    if os.path.exists(os.path.join(CURATION, "coordinate_review.csv")):
        overrides = {f"{r['city']}|{r['name']}": r for r in read_rows(os.path.join(CURATION, "coordinate_review.csv"))}

    city_names = {c["slug"]: c["name"] for c in cities_cur}
    city_names.update({slug: info["title"] for slug, info in ORIGINAL_CENTRES.items()})
    used_slugs = set(original_slugs())

    def unique_slug(base, city):
        slug = base if base not in used_slugs else f"{base}-{city}"
        while slug in used_slugs:
            slug += "-x"
        used_slugs.add(slug)
        return slug

    new_cities, new_starts, new_attractions, new_hours, problems = [], [], [], [], []
    for c in cities_cur:
        slug = c["slug"]
        info = snapshot["cities"][slug]
        catalog = top50[c["catalog_name"]]
        new_cities.append({
            "slug": slug, "name": c["name"], "state": catalog["state_ut"], "region": catalog["region"],
            "top_rank": catalog["rank"], "center_lat": f"{info['lat']:.5f}", "center_lng": f"{info['lng']:.5f}",
            "coord_source": "wikipedia", "tagline": c["tagline"], "description": c["description"],
            "hero_image": "", "catalog_id": catalog["destination_id"]})
        for spec in filter(None, c["starts"].split("|")):
            label = spec.partition("=")[0]
            s = snapshot["starts"].get(f"{slug}|{label}")
            if not s or s.get("lat") is None:
                problems.append(f"{slug}: start point {label} has no coordinates")
                continue
            new_starts.append({"city": slug, "slug": unique_slug(slugify(label) + "-start", slug), "name": label,
                               "lat": f"{s['lat']:.5f}", "lng": f"{s['lng']:.5f}", "coord_source": s["source"]})

    for r in curation + food_rows():
        if r["status"] not in ("map", "osm", "extra"):
            continue
        key = f"{r['city']}|{r['name']}"
        entry = dict(snapshot["attractions"][key])
        if key in overrides:
            entry["coord_choice"] = overrides[key]["use"]
            if overrides[key]["use"] == "manual":
                entry["manual"] = [float(overrides[key]["lat"]), float(overrides[key]["lng"])]
        chosen = choose_coords(entry) if entry.get("coord_choice") != "manual" else (*entry["manual"], "approximate")
        if not chosen:
            problems.append(f"{key}: no coordinates from any source -> left out")
            continue
        lat, lng, coord_source = chosen
        osm_tags = dict(entry.get("osm_tags") or {})
        if entry.get("osm"):
            osm_tags = {**(entry["osm"].get("tags") or {}), **osm_tags}
        d = defaults[r["place_type"]]

        hours = parse_osm_hours(osm_tags.get("opening_hours"))
        visit = int(d["visit_minutes"])
        if hours is not None and any(hours.get(day) for day in range(7)) and \
                any(c - o >= visit for ws in hours.values() for o, c in ws):
            hours_source = "osm"
        else:
            hours = {day: [tuple(int(x[:2]) * 60 + int(x[3:]) for x in w.split("-"))
                           for w in d["windows"].split(";")] for day in range(7)}
            hours_source = "estimate"
        fee, _ = parse_osm_fee(osm_tags)
        fee_source = "osm" if fee is not None else "estimate"
        fee = fee if fee is not None else int(d["fee_inr"])

        views = entry.get("views")
        pop = popularity(views)
        description = (entry.get("extract") or "").strip()
        if description:
            description = re.sub(r"\s+", " ", description)
            if len(description) > 420:
                description = description[:417].rsplit(" ", 1)[0] + "…"
            description_source = "wikipedia"
        else:
            description = (f"Listed among the best-known sights of {city_names[r['city']]} "
                           f"in our team's destination catalog. Location from OpenStreetMap; no encyclopedia summary is available.")
            description_source = "catalog"
        slug = unique_slug(slugify(r["name"].split(" (")[0]), r["city"])
        new_attractions.append({
            "city": r["city"], "slug": slug, "name": r["name"], "lat": f"{lat:.5f}", "lng": f"{lng:.5f}",
            "coord_source": coord_source, "categories": r["categories"], "rating": "", "rating_source": "none",
            "popularity": f"{pop if pop is not None else POPULARITY_NO_ARTICLE:.2f}",
            "popularity_source": "wikipedia_pageviews" if pop is not None else "estimate",
            "pageviews_12m": views or "", "visit_minutes": visit, "duration_source": "estimate",
            "fee_inr": fee, "fee_source": fee_source, "hours_source": hours_source,
            "in_team_catalog": "yes" if r["status"] != "extra" else "no", "data_status": "estimate",
            "wiki_title": (entry.get("title") or "").replace(" ", "_"), "wikidata": entry.get("qid") or "",
            "place_type": r["place_type"], "access": r["access"] or "road", "access_note": r["access_note"],
            "cuisine": r.get("cuisine", ""), "vegetarian": r.get("vegetarian") or "unknown",
            "description_source": description_source,
            "description": description})
        for day in range(7):
            for o, c in hours.get(day, []):
                new_hours.append({"city": r["city"], "slug": slug, "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day],
                                  "open": fmt(o), "close": fmt(c), "last_entry": ""})

    write_merged("cities.csv", new_cities, key="slug")
    write_merged("start_points.csv", new_starts)
    write_merged("attractions.csv", new_attractions, fields=ATTRACTION_FIELDS)
    write_merged("opening_hours.csv", compress_hours(new_hours))
    for p in problems:
        print("problem:", p)
    print(f"{len(new_cities)} cities, {len(new_starts)} start points, {len(new_attractions)} attractions written")


def compress_hours(rows):
    """Merge per-day rows with identical windows into 'Daily' / 'Mon,Tue' rows (keeps the CSV readable)."""
    by_place = {}
    for r in rows:
        by_place.setdefault((r["city"], r["slug"]), {}).setdefault((r["open"], r["close"]), []).append(r["days"])
    out = []
    for (city, slug), windows in by_place.items():
        for (o, c), days in windows.items():
            spec = "Daily" if len(days) == 7 else ",".join(days)
            out.append({"city": city, "slug": slug, "days": spec, "open": o, "close": c, "last_entry": ""})
    return out


def is_original(row):
    """A hand-made row of the four original cities (not something this script generated for them)."""
    return row["city"] in ORIGINAL_CITIES and (row.get("description_source") or "project") == "project"


def original_slugs():
    """Slugs of the original cities' hand-made attractions and start points."""
    slugs = {r["slug"] for r in read_rows(os.path.join(DATA, "attractions.csv")) if is_original(r)}
    slugs |= {r["slug"] for r in read_rows(os.path.join(DATA, "start_points.csv")) if r["city"] in ORIGINAL_CITIES}
    return slugs


def write_merged(name, new_rows, key=None, fields=None):
    """Keep the original four cities' rows as they are; replace every other city's rows with new_rows."""
    path = os.path.join(DATA, name)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames
        old = list(reader)
    city_key = "slug" if key == "slug" else "city"
    # Keep only the original four cities' hand-made rows; everything this script generates (including
    # food and shopping places in those cities) is rebuilt below, so re-running never duplicates anything.
    if key == "slug":
        kept = [r for r in old if r["slug"] in ORIGINAL_CITIES]
    elif name == "attractions.csv":
        kept = [r for r in old if is_original(r)]
    else:
        hand_made = ORIGINAL_SLUGS_CACHE or original_slugs()
        kept = [r for r in old if r["city"] in ORIGINAL_CITIES and r["slug"] in hand_made]
    if name == "cities.csv":
        # Region and Top-50 rank for the original cities come from the same catalog list.
        top50 = {r["destination"].lower(): r for r in read_rows(os.path.join(DATA, "catalog", "top50.csv"))}
        for r in kept:
            info = top50.get(r["name"].lower())
            if info:
                r["region"] = r.get("region") or info["region"]
                r["top_rank"] = r.get("top_rank") or info["rank"]
    if name == "attractions.csv":
        # The original cities' values were chosen by hand: say so explicitly in every provenance column.
        for r in kept:
            for column in ("rating_source", "popularity_source", "duration_source", "fee_source", "hours_source"):
                r[column] = r.get(column) or "illustrative"
            r["access"] = r.get("access") or "road"
            r["vegetarian"] = r.get("vegetarian") or "unknown"
            r["description_source"] = r.get("description_source") or "project"
    fields = fields or list(dict.fromkeys(old_fields + [k for r in new_rows for k in r]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for r in kept + new_rows:
            writer.writerow({k: r.get(k, "") for k in fields})


# --------------------------------------------------------------------------- report

def report():
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)
    print("Coordinate disagreements (> 2 km) and missing coordinates:")
    for key, e in sorted(snapshot["attractions"].items()):
        wiki, wd, osm = e.get("wiki_coords"), e.get("wikidata_coords"), e.get("osm")
        city = snapshot["cities"][e["city"]]
        parts = []
        for label, co in (("wiki", wiki), ("wikidata", wd), ("osm", [osm["lat"], osm["lng"]] if osm else None)):
            if co:
                parts.append(f"{label} {co[0]:.4f},{co[1]:.4f} ({haversine_km(city['lat'], city['lng'], *co):.1f} km from centre)")
        points = [co for co in (wiki, wd, [osm["lat"], osm["lng"]] if osm else None) if co]
        spread = max((haversine_km(*a, *b) for a in points for b in points), default=0)
        if not points or spread > COORD_DISAGREE_KM:
            print(f"  {key:52} spread {spread:6.1f} km | " + " | ".join(parts) + (f" | osm name: {osm['name']}" if osm else ""))


# --------------------------------------------------------------------------- images

def shrink(path, width):
    """Wikimedia serves thumbnails in fixed size steps (a 640 px request may return 960 px at high quality).
    On macOS, resize to `width` with the built-in `sips` tool at normal JPEG quality, keeping the
    result only if it is smaller. Elsewhere the file is left as downloaded."""
    import shutil
    import subprocess
    if not shutil.which("sips") or not path.lower().endswith((".jpg", ".jpeg")):
        return
    tmp = path + ".small.jpg"
    result = subprocess.run(["sips", "-Z", str(width), "-s", "format", "jpeg", "-s", "formatOptions", "normal",
                             path, "--out", tmp], capture_output=True)
    if result.returncode == 0 and os.path.getsize(tmp) < os.path.getsize(path):
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)


def images():
    """Free-licence lead photos (Wikipedia pageimages, pilicense=free) for the new cities.

    Attraction photos are 640 px wide and city banners 1280 px, which keeps the repository small.
    Author and licence go to data/image_credits.csv (shown on the About page). Existing files are kept.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fetch_wikimedia import image_info
    from net import download
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)
    attractions = [r for r in read_rows(os.path.join(DATA, "attractions.csv")) if not is_original(r)]
    by_title = {e.get("title"): e for e in snapshot["attractions"].values() if e.get("title")}
    old = read_rows(os.path.join(DATA, "image_credits.csv"))
    hand_made = original_slugs() | {"hero"}
    credits = [r for r in old if r["city"] in ORIGINAL_CITIES and r["slug"] in hand_made]
    jobs = []
    for slug, city in sorted(snapshot["cities"].items()):
        if city.get("image"):
            jobs.append((slug, "hero", city["image"], 1280, f"images/cities/{slug}"))
    for r in attractions:
        entry = by_title.get(r["wiki_title"].replace("_", " "))
        if entry and entry.get("image"):
            jobs.append((r["city"], r["slug"], entry["image"], 640, f"images/attractions/{r['city']}/{r['slug']}"))
    previous = {(r["city"], r["slug"]): r for r in old}
    for city, slug, file_name, width, stem in jobs:
        done = previous.get((city, slug))
        if done and os.path.exists(os.path.join(ROOT, "static", done["image_path"])):
            credits.append(done)                      # already downloaded and credited: no network call
            continue
        try:
            info = image_info(file_name, width)
        except Exception as exc:
            print(f"  {city}/{slug}: {exc}")
            continue
        if info is None or not info["mime"].startswith("image/") or info["mime"] == "image/svg+xml":
            print(f"  {city}/{slug}: no usable raster image")
            continue
        ext = os.path.splitext(urllib.parse.urlparse(info["url"]).path)[1].lower() or ".jpg"
        rel = stem + ext
        target = os.path.join(ROOT, "static", rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            download(info["url"], target)
            shrink(target, width)
            time.sleep(1.0)
        credits.append({"city": city, "slug": slug, "image_path": rel, "credit": info["artist"],
                        "license": info["license"], "source_url": info["page"]})
        print(f"  {rel}  ({info['license']})")
        time.sleep(0.3)
    with open(os.path.join(DATA, "image_credits.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "slug", "image_path", "credit", "license", "source_url"],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(credits)
    print(f"{len(credits)} credits written")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["fetch", "build", "report", "images"])
    args = parser.parse_args()
    {"fetch": fetch, "build": build, "report": report, "images": images}[args.stage]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
