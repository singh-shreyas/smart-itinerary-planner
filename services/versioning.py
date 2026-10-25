"""Fingerprints that make reproducibility checkable.

Every itinerary carries four short SHA-256 fingerprints:

    inputs    the trip exactly as entered (city, dates, hours, pace, ...)
    data      the CSV files the database was built from (database/migrations.py)
    settings  every planner setting in config.py that can change a plan
    plan      the resulting timeline (days, stops, meals, times)

Rule: same inputs + same data + same settings  =>  same plan.
So if two plans differ, the fingerprints show why: a different input, a
changed dataset or a changed setting -- never chance. Two different strategies
that happen to produce the same timeline get the same plan fingerprint.
"""

import hashlib
import json

import config


def short_hash(obj, length=10):
    text = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def settings_version():
    return short_hash(config.fingerprint_settings())


def plan_signature(itinerary):
    """The plan as plain data: what happens when, day by day (no timings of our own code)."""
    days = []
    for day in itinerary.days:
        entries = []
        for entry in day.timeline:
            if hasattr(entry, "attraction"):
                entries.append(["visit", entry.attraction.slug, entry.arrive, entry.start, entry.end, entry.leave])
            else:
                entries.append(["meal", entry.kind, entry.location_name, entry.start, entry.end])
        days.append({"date": day.date.isoformat(), "depart": day.depart if day.visits else None,
                     "entries": entries, "back": day.return_time})
    return days


def versions(city, itinerary):
    return {
        "inputs": short_hash(itinerary.trip.to_query()),
        "data": (city.data_version or "unknown")[:10],
        "settings": settings_version(),
        "plan": short_hash(plan_signature(itinerary)),
    }
