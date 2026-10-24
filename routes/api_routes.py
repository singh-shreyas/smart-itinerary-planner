"""JSON API: the same data as the pages, for tests, scripts and quick curl checks.

    curl "http://127.0.0.1:5001/api/itinerary?city=delhi&days=2&start_date=2026-11-02"
"""

from flask import Blueprint, abort, current_app, jsonify, request

from database import queries
from database.db import get_db
from routes.helpers import city_data, itinerary_to_dict, jsonable, parse_trip_args, transport_rate
from services.comparison import run_comparison
from services.itinerary_generator import plan_trip
from services.timeutil import WEEKDAY_SHORT, fmt_hhmm

api = Blueprint("api", __name__, url_prefix="/api")


@api.route("/health")
def health():
    return jsonify(status="ok", cities=queries.summary_counts(get_db())["cities"])


@api.route("/cities")
def cities():
    return jsonify([{"slug": c["slug"], "name": c["name"], "state": c["state"],
                     "attractions": c["attraction_count"], "start_points": c["start_count"]}
                    for c in queries.list_cities(get_db())])


@api.route("/cities/<slug>/attractions")
def city_attractions(slug):
    city = city_data(slug)
    if city is None:
        abort(404)
    return jsonify([{
        "slug": a.slug, "name": a.name, "lat": a.lat, "lng": a.lng, "categories": list(a.categories),
        "rating": a.rating, "popularity": a.popularity, "visit_minutes": a.visit_min, "fee_inr": a.fee,
        "data_status": a.data_status,
        "hours": {WEEKDAY_SHORT[d]: [[fmt_hhmm(w.open_min), fmt_hhmm(w.close_min)] for w in ws]
                  for d, ws in sorted(a.hours.items())},
    } for a in sorted(city.attractions.values(), key=lambda a: a.id)])


@api.route("/itinerary")
def itinerary():
    trip, errors, _ = parse_trip_args(request.args)
    if errors:
        return jsonify(errors=errors), 400
    return jsonify(jsonable(itinerary_to_dict(plan_trip(city_data(trip.city), trip, transport_rate()))))


@api.route("/compare")
def compare():
    trip, errors, _ = parse_trip_args(request.args)
    if errors:
        return jsonify(errors=errors), 400
    result = run_comparison(city_data(trip.city), trip, transport_rate(), current_app.config["RESULTS_DIR"])
    for row in result["routing"]:
        row.pop("routes", None)                  # map coordinates are only needed by the page
    return jsonify(jsonable(result))
