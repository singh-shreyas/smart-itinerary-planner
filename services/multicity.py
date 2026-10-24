"""Which cities can share one trip? (multi-city eligibility)

Rule, applied PAIRWISE: a group of cities is allowed only if EVERY pair of
them is within config.MULTI_CITY_MAX_KM (100 km) of each other, measured as the
straight-line (great-circle, haversine) distance between the two city centres.

Why pairwise and not "each within 100 km of the base"? Two cities can each be
90 km from the base city but 180 km from each other (on opposite sides). The
pairwise rule guarantees that any two cities in the trip are close.

Limitations (shown in the interface):
  * straight-line distance is only a proxy -- the road is longer, and hills or
    rivers can make it much longer. Road distance and time come from OSRM when
    the data has an intercity link, and are shown next to the straight-line figure;
  * proximity is not proof of a road: travel times come from the road graph,
    or from a clearly labelled estimate if no link is stored (city_data.py).
"""

import itertools
import math

import config


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def centre_distance_km(a, b):
    """Straight-line km between two city rows (dicts or sqlite rows with center_lat / center_lng)."""
    return haversine_km(a["center_lat"], a["center_lng"], b["center_lat"], b["center_lng"])


def nearby_cities(base, cities, limit_km=None):
    """Cities within limit_km of `base` (straight line), nearest first: [(row, km)]."""
    limit_km = config.MULTI_CITY_MAX_KM if limit_km is None else limit_km
    found = []
    for city in cities:
        if city["slug"] == base["slug"]:
            continue
        km = centre_distance_km(base, city)
        if km <= limit_km:
            found.append((city, round(km, 1)))
    return sorted(found, key=lambda pair: (pair[1], pair[0]["slug"]))


def group_problems(group, limit_km=None):
    """Every pair in `group` farther apart than the limit, as readable messages ([] = the group is allowed)."""
    limit_km = config.MULTI_CITY_MAX_KM if limit_km is None else limit_km
    problems = []
    for a, b in itertools.combinations(group, 2):
        km = centre_distance_km(a, b)
        if km > limit_km:
            problems.append(f"{a['name']} and {b['name']} are {km:.0f} km apart in a straight line "
                            f"(the limit is {limit_km:.0f} km between every pair of cities).")
    return problems


def distance_matrix(cities):
    """{slug: {slug: km}} for the planner page's script (rounded to 0.1 km)."""
    return {a["slug"]: {b["slug"]: round(centre_distance_km(a, b), 1) for b in cities if b["slug"] != a["slug"]}
            for a in cities}
