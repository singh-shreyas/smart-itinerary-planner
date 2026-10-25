"""Small helpers shared by the route modules (keeps each route function short)."""

import csv
import math
import os

from flask import current_app

import config
from database import queries
from database.db import get_db
from services.city_data import get_city_data
from services.i18n import gettext as _
from services.models import MealBreak
from services.multicity import nearby_cities
from services.timeutil import fmt_hhmm
from services.trip_request import parse_trip


def city_data(slug, extra=()):
    """Cached CityData (graph + Dijkstra table) for a city -- or a city plus nearby cities -- or None."""
    return get_city_data(get_db(), current_app.config["DATABASE"], slug, current_app.config["TRAFFIC_FACTOR"],
                         tuple(extra))


def area_for(trip):
    return city_data(trip.city, trip.extra_cities)


def categories():
    return queries.list_categories(get_db())


def category_groups():
    """[(group heading, [category rows])] in file order: the interest picker's layout."""
    groups = {}
    for c in categories():
        groups.setdefault(c["grp"], []).append(c)
    return list(groups.items())


def parse_trip_args(args):
    return parse_trip(args, lambda slugs: city_data(slugs[0], slugs[1:]), {c["slug"] for c in categories()})


def read_catalog(name="destinations.csv"):
    """The team's catalog files (names only), if present."""
    path = os.path.join(current_app.config["DATA_DIR"], "catalog", name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_data_csv(name):
    path = os.path.join(current_app.config["DATA_DIR"], name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not next(iter(r.values()), "").startswith("#")]


TIMING_LABELS = {"road_data": "road data (OSRM)", "sourced": "times from a cited source",
                 "estimated": "estimated from a cited distance and climb", "unknown": "not known"}
ALTERNATIVE_STATUS = {"operating_unverified": "Not used in timings: schedule and availability not verified — "
                                              "verify independently",
                      "planned": "Planned, not operating"}


def access_info(a, city=None):
    """Everything the interface shows about how an attraction is reached (JSON-safe)."""
    point = city.places.get(a.access_point_id) if (city is not None and a.access_point_id) else None
    return {
        "type": a.access_type, "label": a.access_label, "road_access": a.road_access,
        "modes": [m for m in (a.access_modes or "").split(";") if m],
        "timing": a.access_timing, "timing_label": _(TIMING_LABELS.get(a.access_timing, a.access_timing)),
        "timed": a.timed, "note": a.access_note, "source_url": a.access_source_url,
        "access_point": point.name if point else None, "last_mile_m": a.last_mile_m,
        "alternatives": [{"label": x["label"], "modes": x["modes"], "from": x["starts_from"],
                          "minutes": x["minutes"], "status": _(ALTERNATIVE_STATUS[x["status"]]),
                          "note": x["note"], "source_url": x["source_url"]} for x in a.alternatives],
    }


def catalog_only():
    """Catalog names kept out of the planner, with the reason (data/curation/attraction_titles.csv)."""
    path = os.path.join(current_app.config["DATA_DIR"], "curation", "attraction_titles.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["city"].startswith("#") or r["status"] != "skip":
                continue
            reason = r["access_note"]
            if reason.startswith("No reliable location"):        # a data-curation note, not visitor information
                reason = "Not in the planner yet: its exact location still has to be confirmed."
            out.setdefault(r["city"], []).append({"name": r["catalog_name"], "reason": reason})
    return out


def jsonable(value):
    """Replace math.inf / NaN (not valid JSON) with None, recursively."""
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def readiness_by_city():
    """{slug: readiness dict} for every city (uses the cached per-city graphs)."""
    return {c["slug"]: city_data(c["slug"]).readiness() for c in queries.list_cities(get_db())}


def hub_road(slug_a, slug_b):
    """Road km and planned minutes between two cities' main hubs (shortest path in the two-city graph)."""
    from services.city_data import _hub
    area = city_data(slug_a, (slug_b,))
    hub_a, hub_b = _hub(slug_a, area.places), _hub(slug_b, area.places)
    if not hub_a or not hub_b or area.km[hub_a.id][hub_b.id] == math.inf:
        return None
    leg = area.leg(hub_a.id, hub_b.id)
    return {"km": round(area.km[hub_a.id][hub_b.id], 1), "minutes": leg.minutes, "estimated": leg.estimated}


def nearby_options(cities_rows):
    """For the planner: each city's eligible nearby cities with straight-line and road distance between hubs."""
    rows = [dict(c) for c in cities_rows]
    out = {}
    for c in rows:
        near = []
        for other, km in nearby_cities(c, rows):
            road = hub_road(c["slug"], other["slug"])
            near.append({"slug": other["slug"], "name": other["name"], "km": km,
                         "road_km": road["km"] if road and not road["estimated"] else None,
                         "road_min": road["minutes"] if road and not road["estimated"] else None})
        out[c["slug"]] = near
    return out


def map_data(city, itinerary):
    """Coordinates for the Leaflet map (the page works without it)."""
    start = itinerary.start_place
    days = []
    for day in itinerary.days:
        points = []
        number = 0
        for entry in day.timeline:
            if isinstance(entry, MealBreak):
                if entry.venue is not None:
                    points.append({"kind": "meal", "name": f"{entry.label} · {entry.venue.name}",
                                   "lat": entry.venue.lat, "lng": entry.venue.lng,
                                   "time": f"{fmt_hhmm(entry.start)}–{fmt_hhmm(entry.end)}"})
                continue
            number += 1
            a = entry.attraction
            points.append({"kind": "stop", "n": number, "name": a.name, "lat": a.lat, "lng": a.lng,
                           "city": a.city_name, "time": f"{fmt_hhmm(entry.start)}–{fmt_hhmm(entry.end)}"})
        begin = day.start_place or start
        finish = day.end_place or start
        days.append({"index": day.index, "stops": points,
                     "from": {"name": begin.name, "lat": begin.lat, "lng": begin.lng},
                     "to": {"name": finish.name, "lat": finish.lat, "lng": finish.lng}})
    return {"start": {"name": start.name, "lat": start.lat, "lng": start.lng},
            "center": [city.info["center_lat"], city.info["center_lng"]], "days": days,
            "cities": [{"name": c["name"], "lat": c["center_lat"], "lng": c["center_lng"]} for c in city.cities]
            if city.multi_city else []}


def _leg_dict(leg):
    return {"travel_min": leg.minutes, "travel_min_raw": leg.raw_minutes, "travel_km": leg.km, "via": leg.via,
            "intercity": leg.intercity, "estimated": leg.estimated,
            "depart": fmt_hhmm(leg.depart) if leg.depart is not None else None}


def itinerary_to_dict(itinerary):
    """JSON shape of an itinerary for the API."""
    trip = itinerary.trip
    days = []
    for day in itinerary.days:
        timeline = []
        for entry in day.timeline:
            if isinstance(entry, MealBreak):
                timeline.append({"type": "meal", "meal": entry.kind, "start": fmt_hhmm(entry.start),
                                 "end": fmt_hhmm(entry.end), "where": entry.location_name,
                                 "venue": entry.venue.slug if entry.venue else None,
                                 "venue_verified": entry.venue is not None, "at_base": entry.at_base,
                                 "leg": _leg_dict(entry.leg) if entry.leg else None})
            else:
                timeline.append({"type": "visit", "slug": entry.attraction.slug})
        days.append({
            "day": day.index, "date": day.date.isoformat(), "weekday": day.date.strftime("%a"),
            "depart": fmt_hhmm(day.depart), "branch": day.branch, "focus": day.focus,
            "starts_at": day.start_place.slug if day.start_place else trip.start,
            "night_at": day.end_place.slug if day.end_place else trip.start, "moves": day.moves,
            "visits": [{"slug": v.attraction.slug, "name": v.attraction.name, "city": v.attraction.city_slug,
                        "arrive": fmt_hhmm(v.arrive), "start": fmt_hhmm(v.start), "end": fmt_hhmm(v.end),
                        "leave": fmt_hhmm(v.leave), "wait_min": v.wait, "travel_min": v.leg.minutes,
                        "travel_min_raw": v.leg.raw_minutes, "travel_km": v.leg.km, "via": v.leg.via,
                        "intercity": v.leg.intercity, "estimated_travel": v.leg.estimated,
                        "segments": [{"mode": s.mode, "minutes": s.minutes, "km": s.km, "basis": s.basis}
                                     for s in v.leg.segments],
                        "access_min": v.leg.access_min, "ferry_wait_min": v.leg.wait,
                        "access": access_info(v.attraction) if v.attraction.special_access else None,
                        "fee_inr": v.attraction.fee, "score": v.score, "filled": v.attraction.id in day.filled}
                       for v in day.visits],
            "timeline": timeline,
            "return": ({"time": fmt_hhmm(day.return_time), "travel_min": day.return_leg.minutes,
                        "travel_min_raw": day.return_leg.raw_minutes, "travel_km": day.return_leg.km,
                        "intercity": day.return_leg.intercity} if day.return_leg else None),
            "totals": {"score": day.score, "travel_min": day.travel_min, "intercity_min": day.intercity_min,
                       "km": day.km, "sight_min": day.sight_min, "meal_min": day.meal_min,
                       "wait_min": day.wait_min, "buffer_min": day.buffer_min, "free_min": day.free_min,
                       "access_min": day.access_min},
            "empty_reason": day.empty_reason,
            "free_time_notes": day.free_time_notes,
        })
    return {
        "city": trip.city, "also": list(trip.extra_cities), "strategy": trip.strategy, "start": trip.start,
        "end": trip.end_stay, "overnight": trip.overnight,
        "journey": [{"city": s["city"], "stay": s["stay"].slug, "first_day": s["first_day"], "last_day": s["last_day"],
                     "nights": s["nights"]} for s in itinerary.journey],
        "mode": trip.mode, "places_picked": list(trip.places),
        "summary": {"selected": len(itinerary.selected), "scheduled": itinerary.stops,
                    "active_days": len(itinerary.active_days), "trip_days": trip.days,
                    "per_day": [len(d.visits) for d in itinerary.days],
                    "min_days": itinerary.distribution.min_days if itinerary.distribution else None,
                    "notes": itinerary.mode_notes},
        "illustrative": itinerary.illustrative, "runtime_ms": round(itinerary.runtime_ms, 2),
        "travel_rounding_min": config.TRAVEL_ROUNDING_MIN,
        "days": days,
        "totals": {"stops": itinerary.stops, "score": itinerary.score, "travel_min": itinerary.travel_min,
                   "km": itinerary.km, "sight_min": itinerary.sight_min, "meal_min": itinerary.meal_min},
        "skipped": [{"slug": s.attraction.slug, "reason": s.code, "detail": s.reason} for s in itinerary.skipped],
        "estimated_links": [{"from": a, "to": b, "straight_km": km} for a, b, km in itinerary.estimated_links],
        "interest_notes": [n["text"] for n in itinerary.interest_notes],
        "violations": itinerary.violations,
        "versions": itinerary.versions,
    }
