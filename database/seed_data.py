"""Build the SQLite database from the CSV files in data/ (repeatable).

    python -m database.seed_data              # rebuild instance/itinerary.db
    python -m database.seed_data --strict     # also refuse 'illustrative' rows and warnings

The CSV files are the source of truth; the .db file is generated and git-ignored.
Adding a city means adding rows to the CSVs and re-running this script -- no
algorithm code changes.

The script validates the data before inserting anything and refuses to build
the database if a row is invalid (bad coordinates, closing before opening,
a visit that never fits its opening hours, an edge between two cities, ...).
"""

import argparse
import csv
import math
import os
import sqlite3
import sys
from collections import defaultdict

if __package__ in (None, ""):                       # allow "python database/seed_data.py"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.dijkstra import dijkstra             # noqa: E402
from algorithms.graph import build_graph, reverse_graph  # noqa: E402
from config import BASE_DIR, Config                  # noqa: E402

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
STATIC_DIR = os.path.join(BASE_DIR, "static")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_KM_FROM_CENTRE = 60


class SeedError(Exception):
    """Raised with every validation problem found, so they can all be fixed at once."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid data:\n  - " + "\n  - ".join(errors))


# --------------------------------------------------------------------------- helpers

def read_csv(data_dir, name, required=True):
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        if required:
            raise SeedError([f"missing data file {name}"])
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = []
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            values = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not any(values.values()) or next(iter(values.values())).startswith("#"):
                continue
            values["_where"] = f"{name}:{line_no}"
            rows.append(values)
        return rows


def parse_hhmm(text):
    """'09:30' -> 570 minutes after midnight. '24:00' is allowed for closing time."""
    hours, minutes = text.split(":")
    value = int(hours) * 60 + int(minutes)
    if not 0 <= value <= 1440 or not 0 <= int(minutes) < 60:
        raise ValueError(text)
    return value


def parse_days(spec):
    """'Daily', 'Tue-Sun', 'Sat-Thu' (wraps round the week), 'Mon,Wed,Fri' -> weekday numbers."""
    if spec.lower() == "daily":
        return list(range(7))
    days = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            first, last = (WEEKDAYS.index(p.strip()) for p in part.split("-"))
            day = first
            while True:
                days.append(day)
                if day == last:
                    break
                day = (day + 1) % 7
        else:
            days.append(WEEKDAYS.index(part))
    return sorted(set(days))


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- loading + validation

def load_and_validate(data_dir, strict=False):
    """Read every CSV, check it, and return clean records plus warnings."""
    errors, warnings = [], []

    categories = read_csv(data_dir, "categories.csv")
    category_slugs = {c["slug"] for c in categories}

    cities = {}
    for row in read_csv(data_dir, "cities.csv"):
        try:
            row["center_lat"], row["center_lng"] = float(row["center_lat"]), float(row["center_lng"])
            row["catalog_id"] = int(row["catalog_id"]) if row.get("catalog_id") else None
        except ValueError:
            errors.append(f"{row['_where']}: bad number")
            continue
        if row["slug"] in cities:
            errors.append(f"{row['_where']}: duplicate city slug {row['slug']}")
        if row.get("hero_image") and not os.path.exists(os.path.join(STATIC_DIR, row["hero_image"])):
            warnings.append(f"{row['_where']}: hero image {row['hero_image']} not found (placeholder used)")
            row["hero_image"] = ""
        cities[row["slug"]] = row

    places = {}                                     # (city, slug) -> record

    def add_place(row, kind):
        key = (row["city"], row["slug"])
        if row["city"] not in cities:
            errors.append(f"{row['_where']}: unknown city {row['city']}")
            return None
        if key in places:
            errors.append(f"{row['_where']}: duplicate slug {row['slug']} in {row['city']}")
            return None
        try:
            row["lat"], row["lng"] = float(row["lat"]), float(row["lng"])
        except ValueError:
            errors.append(f"{row['_where']}: bad coordinates")
            return None
        city = cities[row["city"]]
        km = haversine_km(row["lat"], row["lng"], city["center_lat"], city["center_lng"])
        if km > MAX_KM_FROM_CENTRE:
            errors.append(f"{row['_where']}: {row['slug']} is {km:.0f} km from the city centre")
        row["kind"] = kind
        places[key] = row
        return row

    for row in read_csv(data_dir, "start_points.csv"):
        add_place(row, "start")

    attractions = {}
    for row in read_csv(data_dir, "attractions.csv"):
        if add_place(row, "attraction") is None:
            continue
        where = row["_where"]
        try:
            row["rating"] = float(row["rating"])
            row["popularity"] = float(row["popularity"])
            row["visit_minutes"] = int(row["visit_minutes"])
            row["fee_inr"] = int(row["fee_inr"])
            row["in_team_catalog"] = 1 if row["in_team_catalog"].lower() in ("yes", "1", "true") else 0
        except ValueError:
            errors.append(f"{where}: bad number")
            continue
        row["categories"] = [c.strip() for c in row["categories"].split(";") if c.strip()]
        if not 0 <= row["rating"] <= 5:
            errors.append(f"{where}: rating must be 0-5")
        if not 0 <= row["popularity"] <= 1:
            errors.append(f"{where}: popularity must be 0-1")
        if not 15 <= row["visit_minutes"] <= 480:
            errors.append(f"{where}: visit_minutes must be 15-480")
        if row["fee_inr"] < 0:
            errors.append(f"{where}: fee cannot be negative")
        if not row["categories"] or set(row["categories"]) - category_slugs:
            errors.append(f"{where}: unknown or missing category in {row['categories']}")
        if row["data_status"] not in ("verified", "estimate", "illustrative"):
            errors.append(f"{where}: data_status must be verified / estimate / illustrative")
        if strict and row["data_status"] == "illustrative":
            errors.append(f"{where}: {row['slug']} is marked illustrative (strict mode)")
        row["hours"] = []
        attractions[(row["city"], row["slug"])] = row

    for row in read_csv(data_dir, "opening_hours.csv"):
        key = (row["city"], row["slug"])
        where = row["_where"]
        if key not in attractions:
            errors.append(f"{where}: hours for unknown attraction {row['slug']}")
            continue
        try:
            days = parse_days(row["days"])
            open_min, close_min = parse_hhmm(row["open"]), parse_hhmm(row["close"])
            last_entry = parse_hhmm(row["last_entry"]) if row.get("last_entry") else None
        except ValueError:
            errors.append(f"{where}: bad day or time format")
            continue
        if open_min >= close_min:
            errors.append(f"{where}: opens at or after closing time")
            continue
        if last_entry is not None and not open_min <= last_entry <= close_min:
            errors.append(f"{where}: last entry outside opening hours")
        for day in days:
            attractions[key]["hours"].append((day, open_min, close_min, last_entry))

    for key, row in attractions.items():
        if not row["hours"]:
            errors.append(f"{row['_where']}: {row['slug']} has no opening hours on any day")
            continue
        def latest_start(close, last):
            latest = close - row["visit_minutes"]
            return latest if last is None else min(latest, last)

        if not any(latest_start(close, last) >= open_ for _, open_, close, last in row["hours"]):
            errors.append(f"{row['_where']}: a {row['visit_minutes']}-minute visit never fits its opening hours")

    edges = []
    for row in read_csv(data_dir, "travel_times.csv", required=False):
        where = row["_where"]
        a, b = (row["city"], row["from_slug"]), (row["city"], row["to_slug"])
        if a not in places or b not in places:
            errors.append(f"{where}: edge uses an unknown place ({row['from_slug']} -> {row['to_slug']})")
            continue
        if a == b:
            errors.append(f"{where}: edge from a place to itself")
            continue
        try:
            minutes, km = float(row["minutes"]), float(row["km"])
        except ValueError:
            errors.append(f"{where}: bad number")
            continue
        if minutes <= 0 or km <= 0:
            errors.append(f"{where}: minutes and km must be positive")
            continue
        if row["source"] not in ("osrm", "manual", "haversine_estimate"):
            errors.append(f"{where}: unknown edge source {row['source']}")
            continue
        edges.append((a, b, minutes, km, row["source"]))

    credits = {}
    for row in read_csv(data_dir, "image_credits.csv", required=False):
        if os.path.exists(os.path.join(STATIC_DIR, row["image_path"])):
            credits[(row["city"], row["slug"])] = row
        else:
            warnings.append(f"{row['_where']}: image {row['image_path']} not found (placeholder used)")

    warnings.extend(_connectivity_warnings(cities, places, edges))
    if strict and warnings:
        errors.extend(f"(strict) {w}" for w in warnings)
    if errors:
        raise SeedError(errors)

    return {"categories": categories, "cities": cities, "places": places,
            "attractions": attractions, "edges": edges, "credits": credits, "warnings": warnings}


def _connectivity_warnings(cities, places, edges):
    """Every attraction should be reachable from, and able to return to, each start point."""
    warnings = []
    for city in cities:
        nodes = [key for key in places if key[0] == city]
        graph = build_graph(nodes, [(a, b, m) for a, b, m, _, _ in edges if a[0] == city])
        backwards = reverse_graph(graph)
        for start in (k for k in nodes if places[k]["kind"] == "start"):
            out_dist, _ = dijkstra(graph, start)
            back_dist, _ = dijkstra(backwards, start)
            for node in nodes:
                if places[node]["kind"] == "attraction" and (out_dist[node] == math.inf or back_dist[node] == math.inf):
                    warnings.append(f"{city}: {node[1]} cannot be reached from and back to {start[1]}")
    return warnings


# --------------------------------------------------------------------------- writing

def seed_database(db_path, data_dir=None, strict=False):
    """Validate the CSVs and (re)build the database file at db_path.

    The new database is written to a temporary file and moved into place at the
    end, so a running app never sees a half-built database.
    """
    data_dir = data_dir or Config.DATA_DIR
    data = load_and_validate(data_dir, strict=strict)

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    tmp_path = db_path + ".building"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())
        with conn:                                   # one transaction for all inserts
            category_ids = {}
            for c in data["categories"]:
                cur = conn.execute("INSERT INTO categories (slug, name, icon) VALUES (?, ?, ?)",
                                   (c["slug"], c["name"], c["icon"]))
                category_ids[c["slug"]] = cur.lastrowid

            city_ids = {}
            for slug, c in data["cities"].items():
                hero = data["credits"].get((slug, "hero"))      # credits row wins over cities.csv
                cur = conn.execute(
                    """INSERT INTO cities (slug, name, state, center_lat, center_lng, tagline,
                                           description, hero_image, hero_credit, hero_source_url, catalog_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (slug, c["name"], c["state"], c["center_lat"], c["center_lng"], c["tagline"],
                     c["description"],
                     hero["image_path"] if hero else (c.get("hero_image") or None),
                     f"{hero['credit']} ({hero['license']})" if hero else None,
                     hero["source_url"] if hero else None,
                     c["catalog_id"]))
                city_ids[slug] = cur.lastrowid

            place_ids = {}
            for key, p in data["places"].items():
                cur = conn.execute(
                    "INSERT INTO places (city_id, slug, name, kind, lat, lng) VALUES (?, ?, ?, ?, ?, ?)",
                    (city_ids[key[0]], p["slug"], p["name"], p["kind"], p["lat"], p["lng"]))
                place_ids[key] = cur.lastrowid

            for key, a in data["attractions"].items():
                credit = data["credits"].get(key)
                conn.execute(
                    """INSERT INTO attractions (place_id, rating, popularity, visit_minutes, fee_inr,
                                                description, image_path, image_credit, image_source_url,
                                                info_url, in_team_catalog, data_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (place_ids[key], a["rating"], a["popularity"], a["visit_minutes"], a["fee_inr"],
                     a["description"],
                     credit["image_path"] if credit else None,
                     f"{credit['credit']} ({credit['license']})" if credit else None,
                     credit["source_url"] if credit else None,
                     f"https://en.wikipedia.org/wiki/{a['wiki_title']}" if a.get("wiki_title") else None,
                     a["in_team_catalog"], a["data_status"]))
                conn.executemany(
                    "INSERT INTO attraction_categories (place_id, category_id) VALUES (?, ?)",
                    [(place_ids[key], category_ids[c]) for c in a["categories"]])
                conn.executemany(
                    """INSERT INTO opening_hours (place_id, weekday, open_min, close_min, last_entry_min)
                       VALUES (?, ?, ?, ?, ?)""",
                    [(place_ids[key], day, o, c, last) for day, o, c, last in a["hours"]])

            conn.executemany(
                "INSERT INTO travel_edges (from_id, to_id, minutes, km, source) VALUES (?, ?, ?, ?, ?)",
                [(place_ids[a], place_ids[b], m, km, src) for a, b, m, km, src in data["edges"]])
    finally:
        conn.close()
    os.replace(tmp_path, db_path)

    return {
        "cities": len(data["cities"]),
        "attractions": len(data["attractions"]),
        "start_points": sum(1 for p in data["places"].values() if p["kind"] == "start"),
        "edges": len(data["edges"]),
        "warnings": data["warnings"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the SQLite database from data/*.csv")
    parser.add_argument("--db", default=Config.DATABASE, help="output database path")
    parser.add_argument("--data", default=Config.DATA_DIR, help="folder with the CSV files")
    parser.add_argument("--strict", action="store_true", help="refuse illustrative rows and warnings")
    args = parser.parse_args(argv)
    try:
        summary = seed_database(args.db, args.data, strict=args.strict)
    except SeedError as exc:
        print(exc, file=sys.stderr)
        return 1
    for warning in summary["warnings"]:
        print(f"warning: {warning}")
    print(f"Built {args.db}: {summary['cities']} cities, {summary['attractions']} attractions, "
          f"{summary['start_points']} start points, {summary['edges']} travel edges.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
