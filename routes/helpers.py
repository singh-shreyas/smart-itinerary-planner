"""Small helpers shared by the route modules (keeps each route function short)."""

import csv
import math
import os

from flask import current_app

from database import queries
from database.db import get_db
from services.city_data import get_city_data
from services.timeutil import fmt_hhmm
from services.trip_request import parse_trip


def city_data(slug):
    """Cached CityData (graph + Dijkstra table) for a city slug, or None."""
    return get_city_data(get_db(), current_app.config["DATABASE"], slug, current_app.config["TRAFFIC_FACTOR"])


def categories():
    return queries.list_categories(get_db())


def parse_trip_args(args):
    return parse_trip(args, city_data, {c["slug"] for c in categories()})


def transport_rate():
    return current_app.config["TRANSPORT_COST_PER_KM"]


def read_catalog():
    """The team's 200-destination catalog (names only), if present."""
    path = os.path.join(current_app.config["DATA_DIR"], "catalog", "destinations.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def jsonable(value):
    """Replace math.inf / NaN (not valid JSON) with None, recursively."""
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def map_data(city, itinerary):
    """Coordinates for the Leaflet map (the page works without it)."""
    start = itinerary.start_place
    days = []
    for day in itinerary.days:
        stops = [{"n": i, "name": v.attraction.name, "lat": v.attraction.lat, "lng": v.attraction.lng,
                  "time": f"{fmt_hhmm(v.start)}–{fmt_hhmm(v.end)}"}
                 for i, v in enumerate(day.visits, start=1)]
        days.append({"index": day.index, "stops": stops})
    return {"start": {"name": start.name, "lat": start.lat, "lng": start.lng},
            "center": [city.info["center_lat"], city.info["center_lng"]], "days": days}


def itinerary_to_dict(itinerary):
    """JSON shape of an itinerary for the API."""
    trip = itinerary.trip
    days = []
    for day in itinerary.days:
        days.append({
            "day": day.index, "date": day.date.isoformat(), "weekday": day.date.strftime("%a"),
            "depart": fmt_hhmm(day.depart), "branch": day.branch,
            "visits": [{"slug": v.attraction.slug, "name": v.attraction.name, "arrive": fmt_hhmm(v.arrive),
                        "start": fmt_hhmm(v.start), "end": fmt_hhmm(v.end), "leave": fmt_hhmm(v.leave),
                        "wait_min": v.wait, "travel_min": v.leg.minutes, "travel_km": v.leg.km,
                        "via": v.leg.via, "fee_inr": v.attraction.fee, "score": v.score}
                       for v in day.visits],
            "return": ({"time": fmt_hhmm(day.return_time), "travel_min": day.return_leg.minutes,
                        "travel_km": day.return_leg.km} if day.visits else None),
            "totals": {"score": day.score, "travel_min": day.travel_min, "km": day.km,
                       "sight_min": day.sight_min, "wait_min": day.wait_min, "fees_inr": day.fees,
                       "transport_inr": day.transport_cost, "spend_inr": day.spend(trip.include_transport)},
            "empty_reason": day.empty_reason,
        })
    return {
        "city": trip.city, "strategy": trip.strategy, "start": trip.start,
        "illustrative": itinerary.illustrative, "runtime_ms": round(itinerary.runtime_ms, 2),
        "days": days,
        "totals": {"stops": itinerary.stops, "score": itinerary.score, "travel_min": itinerary.travel_min,
                   "km": itinerary.km, "sight_min": itinerary.sight_min, "spend_inr": itinerary.spend},
        "skipped": [{"slug": s.attraction.slug, "reason": s.code, "detail": s.reason} for s in itinerary.skipped],
        "violations": itinerary.violations,
    }
