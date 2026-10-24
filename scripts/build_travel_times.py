"""One-off data script: build data/travel_times.csv (the sparse road graph).

    python scripts/build_travel_times.py            # road times from OSRM (needs internet, run once)
    python scripts/build_travel_times.py --offline  # straight-line estimates only (no internet)

For every place we keep directed links to its K nearest neighbours (by
straight-line distance), in both directions. Their driving time and road
distance come from the public OSRM demo server, which routes over
OpenStreetMap roads: one "table" request per city, well inside its fair-use
policy. OSRM times are free-flow (no traffic); the app multiplies them by
TRAFFIC_FACTOR from config.py.

Keeping only local links makes the graph sparse, so Dijkstra has a real job:
the travel time between two far-apart places is composed from local links.
If OSRM has no answer for a pair, a clearly labelled straight-line estimate is
stored instead (source = haversine_estimate).

Routing data (c) OpenStreetMap contributors (ODbL), computed with OSRM.
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

from net import get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
K_NEAREST = 5
DETOUR_FACTOR = 1.35          # straight line -> road distance (fallback only)
FALLBACK_SPEED_KMH = 25       # free-flow city speed (fallback only)


def haversine_km(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlng = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def read_places():
    places = defaultdict(list)
    for name in ("start_points.csv", "attractions.csv"):
        with open(os.path.join(DATA, name), newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                places[row["city"]].append({"slug": row["slug"], "lat": float(row["lat"]), "lng": float(row["lng"])})
    return places


def osrm_table(nodes):
    coords = ";".join(f"{n['lng']:.5f},{n['lat']:.5f}" for n in nodes)
    data = get_json(OSRM_TABLE + coords, {"annotations": "duration,distance"})
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message', '')}")
    return data["durations"], data["distances"]


def sparse_pairs(nodes):
    """K-nearest-neighbour links in both directions, then join any separate components."""
    n = len(nodes)
    straight = [[haversine_km(nodes[i], nodes[j]) for j in range(n)] for i in range(n)]
    pairs = set()
    for i in range(n):
        nearest = sorted((j for j in range(n) if j != i), key=lambda j: (straight[i][j], j))[:K_NEAREST]
        for j in nearest:
            pairs.add((i, j))
            pairs.add((j, i))

    # Union-find style component labels; connect the closest pair across components until one remains.
    while True:
        label = list(range(n))

        def find(x):
            while label[x] != x:
                label[x] = label[label[x]]
                x = label[x]
            return x

        for i, j in pairs:
            label[find(i)] = find(j)
        roots = {find(i) for i in range(n)}
        if len(roots) == 1:
            return pairs
        i, j = min(((i, j) for i in range(n) for j in range(n) if find(i) != find(j)),
                   key=lambda p: straight[p[0]][p[1]])
        pairs.add((i, j))
        pairs.add((j, i))


def build_city(nodes, offline):
    durations = distances = None
    if not offline:
        try:
            durations, distances = osrm_table(nodes)
        except Exception as exc:                       # network down, server busy, ...
            print(f"  OSRM unavailable ({exc}); using straight-line estimates")
    rows = []
    for i, j in sorted(sparse_pairs(nodes)):
        a, b = nodes[i], nodes[j]
        seconds = durations[i][j] if durations else None
        metres = distances[i][j] if distances else None
        if seconds and metres and seconds > 0 and metres > 0:
            minutes, km, source = seconds / 60, metres / 1000, "osrm"
        else:
            km = max(haversine_km(a, b) * DETOUR_FACTOR, 0.05)
            minutes, source = km / FALLBACK_SPEED_KMH * 60, "haversine_estimate"
        rows.append((a["slug"], b["slug"], max(round(minutes, 1), 0.5), max(round(km, 2), 0.05), source))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip OSRM and use straight-line estimates")
    args = parser.parse_args()

    out_rows = []
    for city, nodes in sorted(read_places().items()):
        rows = build_city(nodes, args.offline)
        sources = defaultdict(int)
        for r in rows:
            sources[r[4]] += 1
        print(f"{city}: {len(nodes)} places, {len(rows)} directed links {dict(sources)}")
        out_rows.extend((city,) + r for r in rows)

    with open(os.path.join(DATA, "travel_times.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["city", "from_slug", "to_slug", "minutes", "km", "source"])
        writer.writerows(out_rows)
    print(f"wrote {len(out_rows)} links to data/travel_times.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
