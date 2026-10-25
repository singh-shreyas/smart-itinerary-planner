"""Content pages: home, cities, attractions, about."""

from collections import Counter

from flask import Blueprint, abort, redirect, render_template, request, url_for

import config
from database import queries
from database.db import get_db
from routes.helpers import (access_info, catalog_only, categories, category_groups, city_data, nearby_options,
                            read_catalog, read_data_csv,
                            readiness_by_city)
from services.algorithm_info import ALGORITHMS
from services.city_data import load_attractions
from services.timeutil import WEEKDAY_LONG, fmt_duration

main = Blueprint("main", __name__)

SORTS = {
    "popular": ("Most popular", lambda a: (-a.popularity, a.id)),
    "rating": ("Highest rated", lambda a: (-(a.rating if a.rating is not None else -1), -a.popularity, a.id)),
    "duration": ("Shortest visit", lambda a: (a.visit_min, a.id)),
    "fee": ("Lowest entry fee", lambda a: (a.fee, a.id)),
    "name": ("Name (A–Z)", lambda a: (a.name.lower(), a.id)),
}

SOURCE_LABELS = {
    "wikipedia": "Wikipedia", "wikidata": "Wikidata", "openstreetmap": "OpenStreetMap", "osm": "OpenStreetMap",
    "wikipedia_pageviews": "Wikipedia page views", "estimate": "estimate (typical for this kind of place)",
    "illustrative": "illustrative (chosen by hand)", "approximate": "approximate", "none": "no data",
}


def regions(cities):
    grouped = {}
    for c in cities:
        grouped.setdefault(c["region"] or "Other", []).append(c)
    return sorted(grouped.items())


@main.route("/")
def index():
    conn = get_db()
    cities = queries.list_cities(conn)
    ready = readiness_by_city()
    featured = [c for c in cities if ready[c["slug"]]["status"] == "ready"][:8]
    return render_template("index.html", cities=cities, featured=featured, readiness=ready,
                           counts=queries.summary_counts(conn), algorithms=ALGORITHMS, categories=categories(),
                           ready_count=sum(1 for r in ready.values() if r["status"] == "ready"),
                           regions=regions(cities))


@main.route("/cities")
def cities():
    conn = get_db()
    attractions = load_attractions(conn).values()
    by_city = {}
    for a in attractions:
        by_city.setdefault(a.city_slug, []).append(a)
    category_names = {c["slug"]: c["name"] for c in categories()}
    city_rows = queries.list_cities(conn)
    ready = readiness_by_city()
    near = nearby_options(city_rows)
    skipped = catalog_only()
    city_cards = []
    for city in city_rows:
        items = sorted(by_city.get(city["slug"], []), key=lambda a: (-a.popularity, a.id))
        counts = Counter(c for a in items for c in a.categories)
        city_cards.append({"city": city, "highlights": [a.name for a in items[:3]],
                           "free": sum(1 for a in items if a.fee == 0),
                           "categories": [(category_names[c], n) for c, n in counts.most_common(3)],
                           "readiness": ready[city["slug"]], "nearby": near[city["slug"]],
                           "catalog_only": skipped.get(city["slug"], []),
                           "untimed": [a for a in items if not a.timed]})
    catalog = read_catalog()
    modelled = {str(c["city"]["catalog_id"]) for c in city_cards}
    return render_template("cities.html", city_cards=city_cards, catalog=catalog, regions=regions(city_rows),
                           catalog_states=len({row["state_ut"] for row in catalog}),
                           catalog_attractions=sum(int(row["attraction_count"]) for row in catalog),
                           modelled_ids=modelled,
                           ready_count=sum(1 for r in ready.values() if r["status"] == "ready"))


@main.route("/cities/<slug>")
def city(slug):
    if queries.get_city(get_db(), slug) is None:
        abort(404)
    return redirect(url_for("main.attractions", city=slug))


@main.route("/attractions")
def attractions():
    conn = get_db()
    all_cities = queries.list_cities(conn)
    city_slug = request.args.get("city", "").strip()
    current = next((c for c in all_cities if c["slug"] == city_slug), None)
    if city_slug and current is None:
        abort(404)

    cats = categories()
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    if category not in {c["slug"] for c in cats}:
        category = ""
    sort = request.args.get("sort", "popular")
    if sort not in SORTS:
        sort = "popular"
    open_on = request.args.get("open_on", "").strip()
    open_day = int(open_on) if open_on.isdigit() and int(open_on) < 7 else None

    items = sorted(load_attractions(conn, current["id"] if current else None).values(), key=SORTS[sort][1])

    def matches(a):
        text = f"{a.name} {a.description} {a.city_name}".lower()
        return ((not query or query.lower() in text)
                and (not category or category in a.categories)
                and (open_day is None or bool(a.windows_on(open_day))))

    shown = {a.id for a in items if matches(a)}
    category_names = {c["slug"]: c["name"] for c in cats}
    details = {a.id: attraction_details(a, category_names) for a in items}
    present = Counter(c for a in items for c in a.categories)
    return render_template("attractions.html", cities=all_cities, regions=regions(all_cities), current=current,
                           attractions=items, shown=shown, categories=cats, category_names=category_names,
                           category_groups=category_groups(), present=present, query=query, category=category,
                           sort=sort, sorts=SORTS, open_day=open_day, details=details,
                           readiness=readiness_by_city() if current else None)


def attraction_details(a, category_names):
    """Everything the details dialog shows (embedded as JSON; the page works without it)."""
    hours = []
    for day in range(7):
        windows = a.windows_on(day)
        hours.append([WEEKDAY_LONG[day], " · ".join(w.label() for w in windows) if windows else "Closed"])
    return {
        "name": a.name, "city": a.city_name, "description": a.description,
        "image": url_for("static", filename=a.image) if a.image else None,
        "credit": a.image_credit, "credit_url": a.image_source_url, "info_url": a.info_url,
        "rating": a.rating, "popularity": round(a.popularity * 100), "visit": fmt_duration(a.visit_min),
        "fee": "Free" if a.fee == 0 else f"₹{a.fee}", "categories": [category_names[c] for c in a.categories],
        "hours": hours, "status": a.data_status, "catalog": a.in_team_catalog,
        "access": access_info(a, city_data(a.city_slug)),
        "sources": [["Location", SOURCE_LABELS.get(a.coord_source or "approximate", a.coord_source)],
                    ["Opening hours", SOURCE_LABELS.get(a.hours_source, a.hours_source)],
                    ["Entry fee", SOURCE_LABELS.get(a.fee_source, a.fee_source)],
                    ["Visit length", SOURCE_LABELS.get(a.duration_source, a.duration_source)],
                    ["Rating", SOURCE_LABELS.get(a.rating_source, a.rating_source)],
                    ["Popularity", SOURCE_LABELS.get(a.popularity_source, a.popularity_source)
                     + (f" ({a.pageviews:,} views in 12 months)" if a.pageviews else "")],
                    ["Description", "Wikipedia (CC BY-SA)" if a.description_source == "wikipedia"
                     else ("team catalog" if a.description_source == "catalog" else "written for this project")]],
        "plan_url": url_for("planner.plan", city=a.city_slug),
    }


@main.route("/about")
def about():
    conn = get_db()
    attractions = list(load_attractions(conn).values())
    provenance = {
        "coordinates": Counter(a.coord_source or "approximate" for a in attractions),
        "hours": Counter(a.hours_source for a in attractions),
        "fees": Counter(a.fee_source for a in attractions),
        "ratings": Counter(a.rating_source for a in attractions),
        "popularity": Counter(a.popularity_source for a in attractions),
    }
    credits = sorted(attractions, key=lambda a: (a.city_name, a.name))
    meta = queries.get_meta(conn)
    return render_template("about.html", algorithms=ALGORITHMS, counts=queries.summary_counts(conn),
                           cities=queries.list_cities(conn), provenance=provenance, source_labels=SOURCE_LABELS,
                           credits=credits, catalog_size=len(read_catalog()), defaults=read_data_csv("estimate_defaults.csv"),
                           meta=meta, cfg=config,
                           access_counts=Counter(a.access_timing for a in attractions if a.special_access),
                           access_rows=sorted((a for a in attractions if a.special_access),
                                              key=lambda a: (a.city_name, a.name)),
                           readiness=readiness_by_city())
