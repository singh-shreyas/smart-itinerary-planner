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
from routes.helpers import (area_for, categories, category_groups, city_data, jsonable, map_data, nearby_options,
                            parse_trip_args, readiness_by_city, transport_rate)
from services.comparison import run_comparison
from services.itinerary_generator import plan_trip
from services.timeutil import fmt_hhmm

planner = Blueprint("planner", __name__)

LIST_FIELDS = ("interests", "exclude", "also", "venue_style")


def default_values(city_slug=""):
    lunch, dinner = config.DEFAULT_LUNCH, config.DEFAULT_DINNER
    return {"city": city_slug, "also": [], "start_date": date.today().isoformat(), "days": "2",
            "day_start": config.DEFAULT_DAY_START, "day_end": config.DEFAULT_DAY_END, "budget": "",
            "transport": "", "interests": [], "interest_mode": "prefer", "pace": config.DEFAULT_PACE, "start": "",
            "strategy": config.DEFAULT_STRATEGY, "exclude": [],
            "lunch": "on", "lunch_from": lunch[0], "lunch_to": lunch[1], "lunch_min": str(lunch[2]),
            "dinner": "on", "dinner_from": dinner[0], "dinner_to": dinner[1], "dinner_min": str(dinner[2]),
            "venues": "on", "venue_style": [], "veg": "", "shop_min": "", "shop_spend": ""}


def city_pairs(area):
    """Straight-line distance between every pair of cities in a multi-city trip, plus the road distance
    between their main hubs along the planner's own shortest path (labelled if it is an estimate)."""
    import itertools
    import math
    from services.city_data import _hub
    from services.multicity import centre_distance_km
    pairs = []
    for a, b in itertools.combinations(area.cities, 2):
        hub_a, hub_b = _hub(a["slug"], area.places), _hub(b["slug"], area.places)
        road = area.km[hub_a.id][hub_b.id] if hub_a and hub_b else math.inf
        leg = area.leg(hub_a.id, hub_b.id) if road < math.inf else None
        pairs.append({"a": a["name"], "b": b["name"], "km": round(centre_distance_km(a, b)),
                      "road_km": round(road) if road < math.inf else None,
                      "estimated": bool(leg and leg.estimated), "minutes": leg.minutes if leg else None})
    return pairs


def default_city(cities):
    return "delhi" if any(c["slug"] == "delhi" for c in cities) else (cities[0]["slug"] if cities else "")


def planner_context(values, errors):
    """Everything the trip form needs, including per-city data for its small script."""
    cities = queries.list_cities(get_db())
    ready = readiness_by_city()
    near = nearby_options(cities)
    city_options = {}
    for c in cities:
        data = city_data(c["slug"])
        city_options[c["slug"]] = {
            "name": c["name"], "state": c["state"], "readiness": ready[c["slug"]], "nearby": near[c["slug"]],
            "starts": [{"slug": p.slug, "name": p.name} for p in data.start_points],
            "attractions": [{"slug": a.slug, "name": a.name, "fee": a.fee, "visit": a.visit_min, "city": c["name"],
                             "categories": list(a.categories), "road": a.access == "road"}
                            for a in sorted(data.attractions.values(), key=lambda a: a.name)],
        }
    regions = {}
    for c in cities:
        regions.setdefault(c["region"] or "Other", []).append(c)
    return {"cities": cities, "regions": sorted(regions.items()), "city_options": city_options,
            "categories": categories(), "category_groups": category_groups(), "values": values, "errors": errors,
            "readiness": ready, "meal_durations": config.MEAL_DURATIONS, "venue_styles": config.VENUE_STYLES,
            "shop_minutes": config.SHOP_MINUTES, "interest_modes": config.INTEREST_MODES,
            "multi_city_km": config.MULTI_CITY_MAX_KM, "max_extra": config.MAX_EXTRA_CITIES,
            "objectives": config.STRATEGY_OBJECTIVES}


@planner.route("/plan")
def plan():
    cities = queries.list_cities(get_db())
    values = default_values(default_city(cities))
    # Prefill from the query string (used by "Change preferences" links); validated only on submit.
    for key in values:
        if key in LIST_FIELDS:
            raw = [s for v in request.args.getlist(key) for s in v.split(",") if s]
            values[key] = raw or values[key]
        elif key in ("lunch", "dinner", "venues") and key in request.args:
            values[key] = request.args.getlist(key)[-1]
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
    area = area_for(trip)
    result = plan_trip(area, trip, transport_rate())
    if result.violations:                       # would be a planner bug; never hide it
        current_app.logger.error("Validator found problems: %s", result.violations)
    return render_template("itinerary.html", it=result, trip=trip, city=area,
                           map_data=map_data(area, result), pace=config.PACES[trip.pace],
                           category_names={c["slug"]: c["name"] for c in categories()},
                           rounding=config.TRAVEL_ROUNDING_MIN, fmt_hhmm=fmt_hhmm,
                           city_pairs=city_pairs(area) if area.multi_city else [])


@planner.route("/compare")
def compare():
    args = request.args
    cities = queries.list_cities(get_db())
    if not args.get("city"):
        args = MultiDict({"city": default_city(cities), "days": "2", "start_date": date.today().isoformat()})
    trip, errors, values = parse_trip_args(args)
    if errors:
        return render_template("compare.html", trip=None, result=None, values=values, errors=errors,
                               cities=cities), 400
    area = area_for(trip)
    result = run_comparison(area, trip, transport_rate(), current_app.config["RESULTS_DIR"])
    return render_template("compare.html", trip=trip, city=area, result=result, values=values, errors={},
                           cities=cities, chart_data=jsonable(result), weights=result["weights"],
                           objectives=config.STRATEGY_OBJECTIVES, labels_short=config.STRATEGY_SHORT)
