"""One-off data script: build the sparse road graph (local and intercity links).

    python scripts/build_travel_times.py            # add links for cities that have none yet (needs internet)
    python scripts/build_travel_times.py --all      # rebuild every city's links
    python scripts/build_travel_times.py --offline  # straight-line estimates only (no internet)

Local links: for every place we keep directed links to its K nearest neighbours
(by straight-line distance), in both directions. Their driving time and road
distance come from the public OSRM demo server, which routes over
OpenStreetMap roads: one "table" request per city, well inside its fair-use
policy. OSRM times are free-flow (no traffic); the app multiplies them by
TRAFFIC_FACTOR from config.py.

Keeping only local links makes the graph sparse, so Dijkstra has a real job:
the travel time between two far-apart places is composed from local links.
If OSRM has no answer for a pair, a clearly labelled straight-line estimate is
stored instead (source = haversine_estimate).

Places marked access = no_road (islands, trek-only shrines, ...) get no links,
so the planner reports them as unreachable instead of inventing a road. For
every other place the script prints how far OSRM had to "snap" it to the
nearest road; a large snap distance means the coordinates may be off the road
network and is written to data/curation/road_snap.csv for a human to check.

Intercity links: for every pair of cities whose centres are within the
multi-city limit (100 km straight line), OSRM gives the road time between
their first start points and between the two closest pairs of places across
the cities. They go to data/intercity_times.csv.

Routing data (c) OpenStreetMap contributors (ODbL), computed with OSRM.
"""

import argparse
import csv
import itertools
import math
import os
import sys
import time
from collections import defaultdict

from net import get_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
K_NEAREST = 5
DETOUR_FACTOR = 1.35          # straight line -> road distance (fallback only)
FALLBACK_SPEED_KMH = 25       # free-flow city speed (fallback only)
SNAP_WARN_M = 1500            # coordinates this far from any road deserve a human look
MULTI_CITY_MAX_KM = 100       # keep in step with config.MULTI_CITY_MAX_KM
CROSS_PAIRS = 2               # closest place pairs linked across two nearby cities (plus the hubs)


def haversine_km(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlng = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def read_csv(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_places():
    """{city: [place]} for places with road access, start points first (file order)."""
    places = defaultdict(list)
    for name in ("start_points.csv", "attractions.csv"):
        for row in read_csv(name):
            if (row.get("access") or "road") == "no_road":
                continue
            places[row["city"]].append({"city": row["city"], "slug": row["slug"], "name": row["name"],
                                        "lat": float(row["lat"]), "lng": float(row["lng"]),
                                        "start": name == "start_points.csv"})
    return places


def osrm_table(sources, destinations=None):
    """durations/distances between the points; also the snap distance (m) of every point."""
    points = sources + (destinations or [])
    coords = ";".join(f"{n['lng']:.5f},{n['lat']:.5f}" for n in points)
    params = {"annotations": "duration,distance"}
    if destinations:
        params["sources"] = ";".join(str(i) for i in range(len(sources)))
        params["destinations"] = ";".join(str(i) for i in range(len(sources), len(points)))
    data = get_json(OSRM_TABLE + coords, params)
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message', '')}")
    snaps = [w.get("distance", 0) for w in data["sources"]] + \
            ([w.get("distance", 0) for w in data["destinations"]] if destinations else [])
    return data["durations"], data["distances"], snaps


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
    while n > 1:
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
            break
        i, j = min(((i, j) for i in range(n) for j in range(n) if find(i) != find(j)),
                   key=lambda p: straight[p[0]][p[1]])
        pairs.add((i, j))
        pairs.add((j, i))
    return pairs


def edge(a, b, seconds, metres):
    if seconds and metres and seconds > 0 and metres > 0:
        minutes, km, source = seconds / 60, metres / 1000, "osrm"
    else:
        km = max(haversine_km(a, b) * DETOUR_FACTOR, 0.05)
        minutes, source = km / FALLBACK_SPEED_KMH * 60, "haversine_estimate"
    return max(round(minutes, 1), 0.5), max(round(km, 2), 0.05), source


def build_city(nodes, offline, snap_log):
    durations = distances = None
    if not offline and len(nodes) > 1:
        try:
            durations, distances, snaps = osrm_table(nodes)
            for node, snap in zip(nodes, snaps):
                snap_log.append((node["city"], node["slug"], node["name"], round(snap)))
        except Exception as exc:                       # network down, server busy, ...
            print(f"  OSRM unavailable ({exc}); using straight-line estimates")
    rows = []
    for i, j in sorted(sparse_pairs(nodes)):
        a, b = nodes[i], nodes[j]
        minutes, km, source = edge(a, b, durations[i][j] if durations else None, distances[i][j] if distances else None)
        rows.append((a["slug"], b["slug"], minutes, km, source))
    return rows


def city_centres():
    return {r["slug"]: {"lat": float(r["center_lat"]), "lng": float(r["center_lng"]), "name": r["name"]}
            for r in read_csv("cities.csv")}


def build_intercity(places, offline):
    centres = city_centres()
    rows = []
    for a, b in itertools.combinations(sorted(places), 2):
        if a not in centres or b not in centres or haversine_km(centres[a], centres[b]) > MULTI_CITY_MAX_KM:
            continue
        pa, pb = places[a], places[b]
        pairs = []
        hub_a = next((p for p in pa if p["start"]), pa[0])
        hub_b = next((p for p in pb if p["start"]), pb[0])
        pairs.append((hub_a, hub_b))
        closest = sorted(((x, y) for x in pa for y in pb), key=lambda p: (haversine_km(*p), p[0]["slug"], p[1]["slug"]))
        for x, y in closest:
            if len(pairs) > CROSS_PAIRS:
                break
            if (x, y) not in pairs:
                pairs.append((x, y))
        sources = list({p[0]["slug"]: p[0] for p in pairs}.values())
        targets = list({p[1]["slug"]: p[1] for p in pairs}.values())
        tables = None
        if not offline:
            try:
                there = osrm_table(sources, targets)
                back = osrm_table(targets, sources)
                tables = there, back
                time.sleep(1)
            except Exception as exc:
                print(f"  OSRM unavailable for {a}-{b} ({exc}); using straight-line estimates")
        for x, y in pairs:
            i, j = sources.index(x), targets.index(y)
            m1, k1, s1 = edge(x, y, tables[0][0][i][j] if tables else None, tables[0][1][i][j] if tables else None)
            m2, k2, s2 = edge(y, x, tables[1][0][j][i] if tables else None, tables[1][1][j][i] if tables else None)
            rows.append((a, x["slug"], b, y["slug"], m1, k1, s1))
            rows.append((b, y["slug"], a, x["slug"], m2, k2, s2))
        print(f"  {a}-{b}: {haversine_km(centres[a], centres[b]):.0f} km apart, {len(pairs)} linked pairs")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip OSRM and use straight-line estimates")
    parser.add_argument("--all", action="store_true", help="rebuild cities that already have links")
    args = parser.parse_args()

    places = read_places()
    existing = read_csv("travel_times.csv")
    have = {r["city"] for r in existing}
    out_rows = [] if args.all else [(r["city"], r["from_slug"], r["to_slug"], r["minutes"], r["km"], r["source"])
                                     for r in existing if r["city"] in places]
    snap_log = []
    for city, nodes in sorted(places.items()):
        if city in have and not args.all:
            continue
        rows = build_city(nodes, args.offline, snap_log)
        sources = defaultdict(int)
        for r in rows:
            sources[r[4]] += 1
        print(f"{city}: {len(nodes)} places, {len(rows)} directed links {dict(sources)}")
        out_rows.extend((city,) + r for r in rows)
        time.sleep(1)

    out_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with open(os.path.join(DATA, "travel_times.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["city", "from_slug", "to_slug", "minutes", "km", "source"])
        writer.writerows(out_rows)
    print(f"wrote {len(out_rows)} local links to data/travel_times.csv")

    if snap_log:
        path = os.path.join(DATA, "curation", "road_snap.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["city", "slug", "name", "snap_m"])
            writer.writerows(sorted(snap_log, key=lambda r: -r[3]))
        for city, slug, name, snap in snap_log:
            if snap > SNAP_WARN_M:
                print(f"  check: {city}/{slug} ({name}) is {snap} m from the nearest road")

    inter = build_intercity(places, args.offline)
    with open(os.path.join(DATA, "intercity_times.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["from_city", "from_slug", "to_city", "to_slug", "minutes", "km", "source"])
        writer.writerows(inter)
    print(f"wrote {len(inter)} intercity links to data/intercity_times.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
