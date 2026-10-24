"""Planner pages: the trip form, the generated itinerary and the algorithm comparison.

Generating a plan changes nothing on the server and always gives the same
answer, so these are GET routes: the URL is a shareable, refresh-safe link.
"""

from datetime import date

from flask import Blueprint, abort, current_app, render_template, request
from werkzeug.datastructures import MultiDict

import config
from database import queries
from database.db import get_db
from routes.helpers import categories, city_data, jsonable, map_data, parse_trip_args, transport_rate
from services.comparison import run_comparison
from services.itinerary_generator import plan_trip

planner = Blueprint("planner", __name__)


def default_values(city_slug=""):
    return {"city": city_slug, "start_date": date.today().isoformat(), "days": "2",
            "day_start": config.DEFAULT_DAY_START, "day_end": config.DEFAULT_DAY_END, "budget": "",
            "transport": "", "interests": [], "pace": config.DEFAULT_PACE, "start": "",
            "strategy": config.DEFAULT_STRATEGY, "exclude": []}


def planner_context(values, errors):
    """Everything the trip form needs, including per-city data for its small script."""
    cities = queries.list_cities(get_db())
    city_options = {}
    for c in cities:
        data = city_data(c["slug"])
        city_options[c["slug"]] = {
            "name": c["name"],
            "starts": [{"slug": p.slug, "name": p.name} for p in data.start_points],
            "attractions": [{"slug": a.slug, "name": a.name, "fee": a.fee, "visit": a.visit_min,
                             "days": a.open_weekdays(), "categories": list(a.categories)}
                            for a in sorted(data.attractions.values(), key=lambda a: a.name)],
        }
    return {"cities": cities, "city_options": city_options, "categories": categories(),
            "values": values, "errors": errors}


@planner.route("/plan")
def plan():
    cities = queries.list_cities(get_db())
    default_city = "delhi" if any(c["slug"] == "delhi" for c in cities) else (cities[0]["slug"] if cities else "")
    values = default_values(default_city)
    # Prefill from the query string (used by "Change preferences" links); validated only on submit.
    for key in values:
        if key == "interests":
            values[key] = request.args.getlist(key) or values[key]
        elif key == "exclude":
            values[key] = [s for raw in request.args.getlist(key) for s in raw.split(",") if s] or values[key]
        elif key in request.args:
            values[key] = request.args.get(key, "")
    if not any(c["slug"] == values["city"] for c in cities):
        abort(404)
    return render_template("planner.html", **planner_context(values, {}))


@planner.route("/itinerary")
def itinerary():
    trip, errors, values = parse_trip_args(request.args)
    if errors:
        return render_template("planner.html", **planner_context(values, errors)), 400
    city = city_data(trip.city)
    result = plan_trip(city, trip, transport_rate())
    if result.violations:                       # would be a planner bug; never hide it
        current_app.logger.error("Validator found problems: %s", result.violations)
    return render_template("itinerary.html", it=result, trip=trip, city=city,
                           map_data=map_data(city, result), pace=config.PACES[trip.pace],
                           category_names={c["slug"]: c["name"] for c in categories()})


@planner.route("/compare")
def compare():
    args = request.args
    if not args.get("city"):
        cities = queries.list_cities(get_db())
        default_city = "delhi" if any(c["slug"] == "delhi" for c in cities) else cities[0]["slug"]
        args = MultiDict({"city": default_city, "days": "2", "start_date": date.today().isoformat()})
    trip, errors, values = parse_trip_args(args)
    cities = queries.list_cities(get_db())
    if errors:
        return render_template("compare.html", trip=None, result=None, values=values, errors=errors,
                               cities=cities), 400
    city = city_data(trip.city)
    result = run_comparison(city, trip, transport_rate(), current_app.config["RESULTS_DIR"])
    return render_template("compare.html", trip=trip, city=city, result=result, values=values, errors={},
                           cities=cities, chart_data=jsonable(result))
