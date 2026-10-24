"""Content pages: home, cities, attractions, about."""

import csv
import os
from collections import Counter

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from database import queries
from database.db import get_db
from routes.helpers import categories, read_catalog
from services.algorithm_info import ALGORITHMS
from services.city_data import load_attractions
from services.timeutil import WEEKDAY_LONG, fmt_duration

main = Blueprint("main", __name__)

SORTS = {
    "popular": ("Most popular", lambda a: (-a.popularity, a.id)),
    "rating": ("Highest rated", lambda a: (-a.rating, a.id)),
    "duration": ("Shortest visit", lambda a: (a.visit_min, a.id)),
    "fee": ("Lowest entry fee", lambda a: (a.fee, a.id)),
    "name": ("Name (A–Z)", lambda a: (a.name.lower(), a.id)),
}


@main.route("/")
def index():
    conn = get_db()
    return render_template("index.html", cities=queries.list_cities(conn), counts=queries.summary_counts(conn),
                           algorithms=ALGORITHMS, categories=categories())


@main.route("/cities")
def cities():
    conn = get_db()
    attractions = load_attractions(conn).values()
    by_city = {}
    for a in attractions:
        by_city.setdefault(a.city_slug, []).append(a)
    category_names = {c["slug"]: c["name"] for c in categories()}
    city_cards = []
    for city in queries.list_cities(conn):
        items = sorted(by_city.get(city["slug"], []), key=lambda a: (-a.popularity, a.id))
        counts = Counter(c for a in items for c in a.categories)
        city_cards.append({"city": city, "highlights": [a.name for a in items[:3]],
                           "free": sum(1 for a in items if a.fee == 0),
                           "categories": [(category_names[c], n) for c, n in counts.most_common(4)]})
    catalog = read_catalog()
    modelled = {c["city"]["catalog_id"] for c in city_cards}
    return render_template("cities.html", city_cards=city_cards, catalog=catalog,
                           catalog_states=len({row["state_ut"] for row in catalog}),
                           catalog_attractions=sum(int(row["attraction_count"]) for row in catalog),
                           modelled_ids={str(i) for i in modelled})


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
    return render_template("attractions.html", cities=all_cities, current=current, attractions=items,
                           shown=shown, categories=cats, category_names=category_names, query=query,
                           category=category, sort=sort, sorts=SORTS, open_day=open_day, details=details)


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
        "plan_url": url_for("planner.plan", city=a.city_slug),
    }


@main.route("/about")
def about():
    conn = get_db()
    coord_sources = Counter()
    path = os.path.join(current_app.config["DATA_DIR"], "attractions.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            coord_sources = Counter(row.get("coord_source", "approximate") for row in csv.DictReader(f))
    credits = sorted(load_attractions(conn).values(), key=lambda a: (a.city_name, a.name))
    return render_template("about.html", algorithms=ALGORITHMS, counts=queries.summary_counts(conn),
                           cities=queries.list_cities(conn), coord_sources=coord_sources, credits=credits,
                           catalog_size=len(read_catalog()))
