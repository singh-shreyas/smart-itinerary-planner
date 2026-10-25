"""One-off data script: build the sparse road graph (local and intercity links).

    python scripts/build_travel_times.py            # new cities in full; new places in existing cities only (needs internet)
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

Nodes: the stay areas (data/stay_areas.csv), transport points (stations) and
access points (where a trek or ferry starts), plus every attraction a road
reaches. Attractions with road_access = no in data/access.csv (islands,
trek-only shrines, ...) get no road links: their trek / ferry links are curated
in data/access_segments.csv, never invented here. For every other place the
script records how far OSRM had to "snap" it to the nearest road; a large snap
distance means the coordinates may be off the road network. These go to
data/curation/road_snap.csv (merged with earlier runs) for a human to check.

Intercity links: for every pair of cities whose centres are within the
multi-city limit (100 km straight line), OSRM gives the road time between
their central stay areas and between the two closest pairs of places across
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


STAY_ORDER = ["central", "north", "east", "south", "west"]


def read_places():
    """{city: [place]} for every road node, the central stay area first (it is the city's hub)."""
    off_road = {(r["city"], r["slug"]) for r in read_csv("access.csv") if r.get("road_access") != "yes"}
    stays = sorted(read_csv("stay_areas.csv"),
                   key=lambda r: (r["city"], STAY_ORDER.index(r["direction"]) if r["direction"] in STAY_ORDER else 9))
    places = defaultdict(list)
    for name, rows in (("stay_areas.csv", stays), ("transport_points.csv", read_csv("transport_points.csv")),
                       ("access_points.csv", read_csv("access_points.csv")), ("attractions.csv", read_csv("attractions.csv"))):
        for row in rows:
            if (row["city"], row["slug"]) in off_road:
                continue
            places[row["city"]].append({"city": row["city"], "slug": row["slug"], "name": row["name"],
                                        "lat": float(row["lat"]), "lng": float(row["lng"]),
                                        "start": name == "stay_areas.csv" and row.get("direction") == "central"})
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


def bridge_pairs(nodes, existing_rows, new_pairs):
    """Pairs that join the city's road graph into one piece again (closest pair across pieces), e.g. after
    old start points that held two groups of places together were removed."""
    index = {n["slug"]: i for i, n in enumerate(nodes)}
    pairs = set(new_pairs) | {(index[r["from_slug"]], index[r["to_slug"]]) for r in existing_rows
                              if r["from_slug"] in index and r["to_slug"] in index}
    added = set()
    while True:
        label = list(range(len(nodes)))

        def find(x):
            while label[x] != x:
                label[x] = label[label[x]]
                x = label[x]
            return x

        for i, j in pairs | added:
            label[find(i)] = find(j)
        if len({find(i) for i in range(len(nodes))}) <= 1:
            return added
        i, j = min(((i, j) for i in range(len(nodes)) for j in range(len(nodes)) if find(i) != find(j)),
                   key=lambda p: haversine_km(nodes[p[0]], nodes[p[1]]))
        added |= {(i, j), (j, i)}


def add_new_places(nodes, existing_rows, offline, snap_log):
    """Keep a city's existing links and connect only places that have none yet (each to its K nearest
    places, both directions), so adding a few places never changes the rest of the road graph."""
    linked = {r["from_slug"] for r in existing_rows} | {r["to_slug"] for r in existing_rows}
    fresh = [i for i, n in enumerate(nodes) if n["slug"] not in linked]
    if not fresh and not bridge_pairs(nodes, existing_rows, set()):
        return []
    pairs = set()
    for i in fresh:
        nearest = sorted((j for j in range(len(nodes)) if j != i),
                         key=lambda j: (haversine_km(nodes[i], nodes[j]), j))[:K_NEAREST]
        for j in nearest:
            pairs.add((i, j))
            pairs.add((j, i))
    pairs |= bridge_pairs(nodes, existing_rows, pairs)
    involved = sorted({i for pair in pairs for i in pair})
    sub = [nodes[i] for i in involved]
    durations = distances = None
    if not offline:
        try:
            durations, distances, snaps = osrm_table(sub)
            for node, snap in zip(sub, snaps):
                if node["slug"] in {nodes[i]["slug"] for i in fresh}:
                    snap_log.append((node["city"], node["slug"], node["name"], round(snap)))
        except Exception as exc:
            print(f"  OSRM unavailable ({exc}); using straight-line estimates")
    position = {i: k for k, i in enumerate(involved)}
    rows = []
    for i, j in sorted(pairs):
        a, b = position[i], position[j]
        minutes, km, source = edge(nodes[i], nodes[j], durations[a][b] if durations else None,
                                   distances[a][b] if distances else None)
        rows.append((nodes[i]["slug"], nodes[j]["slug"], minutes, km, source))
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
    known = {(city, n["slug"]) for city, nodes in places.items() for n in nodes}
    # A place that MOVED (same slug, new coordinates -- e.g. a re-chosen stay area) must not keep its old
    # travel times: its links are dropped and computed again. Coordinates of the last run are kept in
    # data/curation/link_nodes.csv; without that file every stay area counts as moved.
    previous = {(r["city"], r["slug"]): (r["lat"], r["lng"]) for r in read_csv(os.path.join("curation", "link_nodes.csv"))}
    stays = {(r["city"], r["slug"]) for r in read_csv("stay_areas.csv")}
    moved = {(city, n["slug"]) for city, nodes in places.items() for n in nodes
             if (previous and previous.get((city, n["slug"])) not in (None, (f"{n['lat']:.6f}", f"{n['lng']:.6f}")))
             or (not previous and (city, n["slug"]) in stays)}
    if moved:
        print(f"{len(moved)} places moved or are new stay areas: their links are recomputed")
    # Links to places that no longer exist (or lost road access), or that moved, are dropped.
    existing = [r for r in read_csv("travel_times.csv")
                if (r["city"], r["from_slug"]) in known and (r["city"], r["to_slug"]) in known
                and (r["city"], r["from_slug"]) not in moved and (r["city"], r["to_slug"]) not in moved]
    have = {r["city"] for r in existing}
    out_rows = [] if args.all else [(r["city"], r["from_slug"], r["to_slug"], r["minutes"], r["km"], r["source"])
                                     for r in existing if r["city"] in places]
    snap_log = []
    for city, nodes in sorted(places.items()):
        if city in have and not args.all:
            rows = add_new_places(nodes, [r for r in existing if r["city"] == city], args.offline, snap_log)
            if rows:
                print(f"{city}: {len(rows)} links added for new places (existing links kept)")
                out_rows.extend((city,) + r for r in rows)
                time.sleep(1)
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
        merged = {(r["city"], r["slug"]): (r["city"], r["slug"], r["name"], int(r["snap_m"]))
                  for r in read_csv(os.path.join("curation", "road_snap.csv"))
                  if (r["city"], r["slug"]) in known}                 # earlier runs' places that still exist
        merged.update({(c, s): (c, s, n, m) for c, s, n, m in snap_log})
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["city", "slug", "name", "snap_m"])
            writer.writerows(sorted(merged.values(), key=lambda r: (-r[3], r[0], r[1])))
        for city, slug, name, snap in snap_log:
            if snap > SNAP_WARN_M:
                print(f"  check: {city}/{slug} ({name}) is {snap} m from the nearest road")

    with open(os.path.join(DATA, "curation", "link_nodes.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["city", "slug", "lat", "lng"])
        writer.writerows(sorted((city, n["slug"], f"{n['lat']:.6f}", f"{n['lng']:.6f}")
                                for city, nodes in places.items() for n in nodes))

    inter = build_intercity(places, args.offline)
    with open(os.path.join(DATA, "intercity_times.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["from_city", "from_slug", "to_city", "to_slug", "minutes", "km", "source"])
        writer.writerows(inter)
    print(f"wrote {len(inter)} intercity links to data/intercity_times.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
