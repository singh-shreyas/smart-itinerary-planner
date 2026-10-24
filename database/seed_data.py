"""Build the SQLite database from the CSV files in data/ (repeatable and safe).

    python -m database.seed_data              # rebuild instance/itinerary.db (old file backed up)
    python -m database.seed_data --check      # only report whether a rebuild is needed
    python -m database.seed_data --strict     # also refuse 'illustrative' rows and warnings

The CSV files are the source of truth; the .db file is generated and git-ignored.
Adding a city means adding rows to the CSVs and re-running this script -- no
algorithm code changes.

The script validates the data before inserting anything and refuses to build
the database if a row is invalid (bad coordinates, closing before opening,
a visit that never fits its opening hours, a duplicate slug, ...). Rebuilding
never loses user data: see database/migrations.py.
"""

import argparse
import csv
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

if __package__ in (None, ""):                       # allow "python database/seed_data.py"
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.dijkstra import dijkstra             # noqa: E402
from algorithms.graph import build_graph, reverse_graph  # noqa: E402
from config import BASE_DIR, Config                  # noqa: E402
from database import migrations                      # noqa: E402

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
STATIC_DIR = os.path.join(BASE_DIR, "static")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Coordinates further than this from the city centre are refused as probable
# mistakes. 110 km allows real day-trip sights such as the Ajanta Caves
# (about 100 km from Chhatrapati Sambhajinagar / Aurangabad).
MAX_KM_FROM_CENTRE = 110
EDGE_SOURCES = ("osrm", "manual", "haversine_estimate")
VALUE_SOURCES = ("wikipedia", "wikidata", "openstreetmap", "osm", "wikipedia_pageviews", "estimate", "illustrative",
                 "approximate", "none")


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


def _source(row, key, default, errors):
    value = row.get(key) or default
    if value not in VALUE_SOURCES:
        errors.append(f"{row['_where']}: {key} must be one of {', '.join(VALUE_SOURCES)}")
    return value


# --------------------------------------------------------------------------- loading + validation

def load_and_validate(data_dir, strict=False):
    """Read every CSV, check it, and return clean records plus warnings."""
    errors, warnings = [], []

    categories = []
    for row in read_csv(data_dir, "categories.csv"):
        row.setdefault("grp", "")
        row["grp"] = row["grp"] or "Other"
        row["parent"] = row.get("parent") or None
        row["kind"] = row.get("kind") or "sight"
        if row["kind"] not in ("sight", "food", "shopping"):
            errors.append(f"{row['_where']}: kind must be sight / food / shopping")
        categories.append(row)
    category_slugs = {c["slug"] for c in categories}
    for c in categories:
        if c["parent"] and c["parent"] not in category_slugs:
            errors.append(f"{c['_where']}: unknown parent category {c['parent']}")

    cities = {}
    for row in read_csv(data_dir, "cities.csv"):
        try:
            row["center_lat"], row["center_lng"] = float(row["center_lat"]), float(row["center_lng"])
            row["catalog_id"] = int(row["catalog_id"]) if row.get("catalog_id") else None
            row["top_rank"] = int(row["top_rank"]) if row.get("top_rank") else None
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
    slug_owner = {}                                 # slug -> city (slugs are unique across cities)

    def add_place(row, kind):
        key = (row["city"], row["slug"])
        if row["city"] not in cities:
            errors.append(f"{row['_where']}: unknown city {row['city']}")
            return None
        if row["slug"] in slug_owner:
            errors.append(f"{row['_where']}: duplicate slug {row['slug']} (already used in {slug_owner[row['slug']]})")
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
        row["access"] = row.get("access") or "road"
        if row["access"] not in ("road", "no_road"):
            errors.append(f"{row['_where']}: access must be road or no_road")
        row["coord_source"] = row.get("coord_source") or None
        places[key] = row
        slug_owner[row["slug"]] = row["city"]
        return row

    for row in read_csv(data_dir, "start_points.csv"):
        add_place(row, "start")

    attractions = {}
    for row in read_csv(data_dir, "attractions.csv"):
        if add_place(row, "attraction") is None:
            continue
        where = row["_where"]
        try:
            row["rating"] = float(row["rating"]) if row.get("rating") else None
            row["popularity"] = float(row["popularity"])
            row["visit_minutes"] = int(row["visit_minutes"])
            row["fee_inr"] = int(row["fee_inr"])
            row["pageviews_12m"] = int(row["pageviews_12m"]) if row.get("pageviews_12m") else None
            row["in_team_catalog"] = 1 if row["in_team_catalog"].lower() in ("yes", "1", "true") else 0
        except ValueError:
            errors.append(f"{where}: bad number")
            continue
        status = row["data_status"]
        if status not in ("verified", "estimate", "illustrative"):
            errors.append(f"{where}: data_status must be verified / estimate / illustrative")
        row["rating_source"] = _source(row, "rating_source", "none" if row["rating"] is None else status, errors)
        if row["rating"] is None and row["rating_source"] != "none":
            errors.append(f"{where}: an empty rating must have rating_source none")
        for key in ("popularity_source", "duration_source", "fee_source", "hours_source"):
            row[key] = _source(row, key, status, errors)
        row["vegetarian"] = row.get("vegetarian") or "unknown"
        if row["vegetarian"] not in ("yes", "unknown"):
            errors.append(f"{where}: vegetarian must be yes or unknown (we never guess 'no')")
        row["categories"] = [c.strip() for c in row["categories"].split(";") if c.strip()]
        if row["rating"] is not None and not 0 <= row["rating"] <= 5:
            errors.append(f"{where}: rating must be 0-5")
        if not 0 <= row["popularity"] <= 1:
            errors.append(f"{where}: popularity must be 0-1")
        if not 15 <= row["visit_minutes"] <= 480:
            errors.append(f"{where}: visit_minutes must be 15-480")
        if row["fee_inr"] < 0:
            errors.append(f"{where}: fee cannot be negative")
        if not row["categories"] or set(row["categories"]) - category_slugs:
            errors.append(f"{where}: unknown or missing category in {row['categories']}")
        if strict and status == "illustrative":
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

    def add_edge(row, a, b, scope):
        where = row["_where"]
        if a not in places or b not in places:
            errors.append(f"{where}: edge uses an unknown place ({a[1]} -> {b[1]})")
            return
        if a == b:
            errors.append(f"{where}: edge from a place to itself")
            return
        if "no_road" in (places[a]["access"], places[b]["access"]):
            errors.append(f"{where}: edge touches a place marked no_road ({a[1]} -> {b[1]})")
            return
        try:
            minutes, km = float(row["minutes"]), float(row["km"])
        except ValueError:
            errors.append(f"{where}: bad number")
            return
        if minutes <= 0 or km <= 0:
            errors.append(f"{where}: minutes and km must be positive")
            return
        if row["source"] not in EDGE_SOURCES:
            errors.append(f"{where}: unknown edge source {row['source']}")
            return
        edges.append((a, b, minutes, km, row["source"], scope))

    for row in read_csv(data_dir, "travel_times.csv", required=False):
        add_edge(row, (row["city"], row["from_slug"]), (row["city"], row["to_slug"]), "local")
    for row in read_csv(data_dir, "intercity_times.csv", required=False):
        if row["from_city"] == row["to_city"]:
            errors.append(f"{row['_where']}: an intercity edge must join two different cities")
            continue
        add_edge(row, (row["from_city"], row["from_slug"]), (row["to_city"], row["to_slug"]), "intercity")

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
    """Every road-accessible attraction should be reachable from, and able to return to, each start point."""
    warnings = []
    for city in cities:
        nodes = [key for key in places if key[0] == city]
        graph = build_graph(nodes, [(a, b, m) for a, b, m, _, _, scope in edges if a[0] == city and scope == "local"])
        backwards = reverse_graph(graph)
        for start in (k for k in nodes if places[k]["kind"] == "start"):
            out_dist, _ = dijkstra(graph, start)
            back_dist, _ = dijkstra(backwards, start)
            for node in nodes:
                place = places[node]
                if place["kind"] != "attraction" or place["access"] == "no_road":
                    continue
                if out_dist[node] == math.inf or back_dist[node] == math.inf:
                    warnings.append(f"{city}: {node[1]} cannot be reached from and back to {start[1]}")
    return warnings


# --------------------------------------------------------------------------- writing

def _write(conn, data, fingerprint):
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    with conn:                                   # one transaction for all inserts
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
            ("schema_version", str(migrations.SCHEMA_VERSION)),
            ("dataset_fingerprint", fingerprint),
            ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ])
        category_ids = {}
        for c in data["categories"]:
            cur = conn.execute("INSERT INTO categories (slug, name, icon, grp, parent, kind) VALUES (?, ?, ?, ?, ?, ?)",
                               (c["slug"], c["name"], c["icon"], c["grp"], c["parent"], c["kind"]))
            category_ids[c["slug"]] = cur.lastrowid

        city_ids = {}
        for slug, c in data["cities"].items():
            hero = data["credits"].get((slug, "hero"))      # credits row wins over cities.csv
            cur = conn.execute(
                """INSERT INTO cities (slug, name, state, region, top_rank, center_lat, center_lng, coord_source,
                                       tagline, description, hero_image, hero_credit, hero_source_url, catalog_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (slug, c["name"], c["state"], c.get("region") or None, c["top_rank"], c["center_lat"], c["center_lng"],
                 c.get("coord_source") or None, c["tagline"], c["description"],
                 hero["image_path"] if hero else (c.get("hero_image") or None),
                 f"{hero['credit']} ({hero['license']})" if hero else None,
                 hero["source_url"] if hero else None,
                 c["catalog_id"]))
            city_ids[slug] = cur.lastrowid

        place_ids = {}
        for key, p in data["places"].items():
            cur = conn.execute(
                """INSERT INTO places (city_id, slug, name, kind, lat, lng, coord_source, access, access_note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (city_ids[key[0]], p["slug"], p["name"], p["kind"], p["lat"], p["lng"], p["coord_source"],
                 p["access"], p.get("access_note") or None))
            place_ids[key] = cur.lastrowid

        for key, a in data["attractions"].items():
            credit = data["credits"].get(key)
            conn.execute(
                """INSERT INTO attractions (place_id, rating, rating_source, popularity, popularity_source,
                                            pageviews_12m, visit_minutes, duration_source, fee_inr, fee_source,
                                            hours_source, description, description_source, image_path,
                                            image_credit, image_source_url, info_url, wikidata, place_type,
                                            cuisine, vegetarian, in_team_catalog, data_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (place_ids[key], a["rating"], a["rating_source"], a["popularity"], a["popularity_source"],
                 a["pageviews_12m"], a["visit_minutes"], a["duration_source"], a["fee_inr"], a["fee_source"],
                 a["hours_source"], a["description"], a.get("description_source") or None,
                 credit["image_path"] if credit else None,
                 f"{credit['credit']} ({credit['license']})" if credit else None,
                 credit["source_url"] if credit else None,
                 f"https://en.wikipedia.org/wiki/{a['wiki_title']}" if a.get("wiki_title") else None,
                 a.get("wikidata") or None, a.get("place_type") or None, a.get("cuisine") or None,
                 a["vegetarian"], a["in_team_catalog"], a["data_status"]))
            conn.executemany(
                "INSERT INTO attraction_categories (place_id, category_id) VALUES (?, ?)",
                [(place_ids[key], category_ids[c]) for c in dict.fromkeys(a["categories"])])
            conn.executemany(
                """INSERT INTO opening_hours (place_id, weekday, open_min, close_min, last_entry_min)
                   VALUES (?, ?, ?, ?, ?)""",
                [(place_ids[key], day, o, c, last) for day, o, c, last in a["hours"]])

        conn.executemany(
            "INSERT INTO travel_edges (from_id, to_id, minutes, km, source, scope) VALUES (?, ?, ?, ?, ?, ?)",
            [(place_ids[a], place_ids[b], m, km, src, scope) for a, b, m, km, src, scope in data["edges"]])


def seed_database(db_path, data_dir=None, strict=False, keep_backups=None):
    """Validate the CSVs and (re)build the database file at db_path.

    The new database is written to a temporary file; user tables from the old
    file are copied in; the old file is backed up; then the new file is moved
    into place. A running app never sees a half-built database, and a failed
    build leaves the old database untouched.
    """
    data_dir = data_dir or Config.DATA_DIR
    keep_backups = Config.DB_BACKUPS_KEPT if keep_backups is None else keep_backups
    data = load_and_validate(data_dir, strict=strict)
    fingerprint = migrations.dataset_fingerprint(data_dir)

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    tmp_path = db_path + ".building"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    try:
        _write(conn, data, fingerprint)
        with conn:
            preserved = migrations.copy_user_tables(db_path, conn)
    except Exception:
        conn.close()
        os.remove(tmp_path)
        raise
    conn.close()
    backup_path = migrations.backup(db_path, keep_backups) if os.path.exists(db_path) else None
    os.replace(tmp_path, db_path)

    return {
        "cities": len(data["cities"]),
        "attractions": len(data["attractions"]),
        "start_points": sum(1 for p in data["places"].values() if p["kind"] == "start"),
        "edges": len(data["edges"]),
        "warnings": data["warnings"],
        "fingerprint": fingerprint,
        "preserved_tables": preserved,
        "backup": backup_path,
    }


def ensure_database(db_path, data_dir, logger=None):
    """Rebuild the database only if it is missing or out of date. Returns the reason, or None."""
    reason = migrations.rebuild_reason(db_path, data_dir)
    if reason is None:
        return None
    summary = seed_database(db_path, data_dir)
    if logger:
        logger.info("Rebuilt database (%s): %s cities, %s attractions%s%s", reason, summary["cities"],
                    summary["attractions"],
                    f"; kept user tables {summary['preserved_tables']}" if summary["preserved_tables"] else "",
                    f"; backup at {summary['backup']}" if summary["backup"] else "")
    return reason


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the SQLite database from data/*.csv")
    parser.add_argument("--db", default=Config.DATABASE, help="output database path")
    parser.add_argument("--data", default=Config.DATA_DIR, help="folder with the CSV files")
    parser.add_argument("--strict", action="store_true", help="refuse illustrative rows and warnings")
    parser.add_argument("--check", action="store_true", help="only say whether a rebuild is needed")
    args = parser.parse_args(argv)
    if args.check:
        reason = migrations.rebuild_reason(args.db, args.data)
        meta = migrations.read_meta(args.db)
        print(f"schema {meta.get('schema_version', '-')}, data {meta.get('dataset_fingerprint', '-')[:12]}, "
              f"built {meta.get('built_at', '-')}")
        print(f"rebuild needed: {reason}" if reason else "up to date")
        return 0
    try:
        summary = seed_database(args.db, args.data, strict=args.strict)
    except SeedError as exc:
        print(exc, file=sys.stderr)
        return 1
    for warning in summary["warnings"]:
        print(f"warning: {warning}")
    print(f"Built {args.db}: {summary['cities']} cities, {summary['attractions']} attractions, "
          f"{summary['start_points']} start points, {summary['edges']} travel edges "
          f"(data {summary['fingerprint'][:12]}).")
    if summary["backup"]:
        print(f"Previous database saved to {summary['backup']}")
    if summary["preserved_tables"]:
        print(f"User tables carried over: {', '.join(summary['preserved_tables'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
