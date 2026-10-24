"""Load one city -- or a group of nearby cities -- from SQLite and prepare the planner's tables.

Done once per city (or city group) and cached in memory:
    1. load places, attractions, opening hours and road links from SQLite
       (for a group: every city's local links plus the intercity links between them)
    2. build the adjacency list (graph.py)
    3. run Dijkstra from every place (dijkstra.py) -> travel-time table + paths
    4. round every shortest-path time UP to 10 minutes -> the planning table

Edge minutes in the database are free-flow OSRM times. Here they are multiplied
by the configured traffic factor and rounded UP to whole minutes, so every
travel time in the planner is an integer and timelines add up exactly.

Two tables come out of step 3/4 and are kept apart on purpose:
    dist[u][v]  raw shortest minutes   -> used to compare and optimise route orders
    plan[u][v]  dist rounded up to 10  -> used for the schedule, feasibility and display
"""

import itertools
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

import config
from algorithms.dijkstra import all_pairs_shortest_paths, reconstruct_path
from algorithms.graph import build_graph, edge_count
from database import queries
from services.models import Attraction, Leg, Place, Window
from services.timeutil import round_up_travel


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


@dataclass
class CityData:
    """Everything the planner needs for one city or a group of nearby cities."""
    slug: str                         # "agra", or "agra+mathura" for a group (base city first)
    name: str
    state: str
    info: dict                        # the base city's row (centre, hero image, ...)
    cities: list                      # [city row dict], base city first
    places: dict                      # place id -> Place (attractions and start points)
    attractions: dict                 # place id -> Attraction
    start_points: list                # [Place] of the base city
    graph: dict                       # adjacency list: id -> [(neighbour id, minutes)]
    edge_km: dict                     # (u, v) -> road km of that direct link
    edge_sources: dict                # source name -> number of links
    estimated_edges: set              # (u, v) links that are straight-line estimates, not road data
    dist: dict                        # dist[u][v] = raw shortest minutes (math.inf if no path)
    plan: dict                        # plan[u][v] = dist rounded up to 10 minutes (the schedule uses this)
    prev: dict                        # prev[u] = Dijkstra predecessor map from u
    km: dict                          # km[u][v] = road km along that shortest path
    traffic_factor: float
    city_of: dict = field(default_factory=dict)          # place id -> city slug
    estimated_links: list = field(default_factory=list)  # [(city a, city b, km)] joined by an estimate
    categories: dict = field(default_factory=dict)       # category slug -> {name, parent, kind, grp, icon}
    data_version: str = ""                               # fingerprint of the CSV files the DB was built from
    build_ms: float = 0.0
    by_slug: dict = field(default_factory=dict)

    @property
    def vertex_count(self):
        return len(self.graph)

    @property
    def edge_count(self):
        return edge_count(self.graph)

    @property
    def city_slugs(self):
        return [c["slug"] for c in self.cities]

    @property
    def multi_city(self):
        return len(self.cities) > 1

    def place(self, slug):
        return self.by_slug.get(slug)

    def attraction_by_slug(self, slug):
        place = self.by_slug.get(slug)
        return self.attractions.get(place.id) if place else None

    def path(self, u, v):
        return reconstruct_path(self.prev[u], u, v)

    def leg(self, u, v, depart=None, purpose="travel"):
        """Travel u -> v along Dijkstra's shortest path, with planned (rounded) and raw minutes."""
        path = self.path(u, v)
        via = [self.places[node].name for node in path[1:-1]]
        estimated = any((a, b) in self.estimated_edges for a, b in zip(path, path[1:]))
        return Leg(from_id=u, to_id=v, minutes=self.plan[u][v], km=round(self.km[u][v], 2), via=via,
                   raw_minutes=self.dist[u][v], intercity=self.city_of.get(u) != self.city_of.get(v),
                   estimated=estimated, depart=depart, purpose=purpose)

    def readiness(self):
        """Can this city actually be planned? Counts attractions reachable from the first start point and back."""
        total = len(self.attractions)
        no_road = sum(1 for a in self.attractions.values() if a.access == "no_road")
        hub = self.start_points[0].id if self.start_points else None
        reachable = 0
        if hub is not None:
            reachable = sum(1 for a in self.attractions
                            if self.dist[hub][a] < math.inf and self.dist[a][hub] < math.inf)
        status = "ready" if reachable >= 3 else ("limited" if reachable else "not_ready")
        return {"status": status, "reachable": reachable, "total": total, "no_road": no_road}


def _attractions_from_rows(rows, hour_rows, category_kinds):
    hours = defaultdict(lambda: defaultdict(list))
    for h in hour_rows:
        hours[h["place_id"]][h["weekday"]].append(Window(h["open_min"], h["close_min"], h["last_entry_min"]))
    attractions = {}
    for r in rows:
        weekly = {day: sorted(ws, key=lambda w: w.open_min) for day, ws in hours[r["id"]].items()}
        categories = tuple(sorted(r["category_slugs"].split(","))) if r["category_slugs"] else ()
        attractions[r["id"]] = Attraction(
            id=r["id"], slug=r["slug"], name=r["name"], lat=r["lat"], lng=r["lng"],
            rating=r["rating"], popularity=r["popularity"], visit_min=r["visit_minutes"], fee=r["fee_inr"],
            categories=categories, hours=weekly, description=r["description"], image=r["image_path"],
            image_credit=r["image_credit"], image_source_url=r["image_source_url"], info_url=r["info_url"],
            data_status=r["data_status"], in_team_catalog=bool(r["in_team_catalog"]),
            city_slug=r["city_slug"], city_name=r["city_name"],
            rating_source=r["rating_source"], popularity_source=r["popularity_source"],
            duration_source=r["duration_source"], fee_source=r["fee_source"], hours_source=r["hours_source"],
            coord_source=r["coord_source"], description_source=r["description_source"],
            pageviews=r["pageviews_12m"], wikidata=r["wikidata"], place_type=r["place_type"],
            cuisine=tuple(s for s in (r["cuisine"] or "").split(";") if s), vegetarian=r["vegetarian"],
            access=r["access"], access_note=r["access_note"],
            kinds=frozenset(category_kinds.get(c, "sight") for c in categories),
        )
    return attractions


def category_kinds(conn):
    return {c["slug"]: c["kind"] for c in queries.list_categories(conn)}


def load_attractions(conn, city_id=None):
    """Attraction objects (with weekly hours) for one city id, a list of ids, or all cities."""
    return _attractions_from_rows(queries.list_attractions(conn, city_id),
                                  queries.list_opening_hours(conn, city_id), category_kinds(conn))


def _hub(city_slug, places):
    """The point used to join two cities when we must estimate: the first start point, else any road place."""
    candidates = [p for p in places.values() if p.city_slug == city_slug and p.access == "road"]
    starts = [p for p in candidates if p.kind == "start"]
    pool = starts or candidates
    return min(pool, key=lambda p: p.id) if pool else None


def load_area(conn, slugs, traffic_factor=1.0):
    """Build a CityData for one city or a group of cities (base city first). None if any slug is unknown."""
    rows = []
    for slug in slugs:
        city = queries.get_city(conn, slug)
        if city is None:
            return None
        rows.append(dict(city))
    started = time.perf_counter()
    ids = [c["id"] for c in rows]
    base = rows[0]

    places = {r["id"]: Place(r["id"], r["slug"], r["name"], r["kind"], r["lat"], r["lng"], r["city_slug"],
                             r["city_name"], r["access"], r["access_note"])
              for r in queries.list_places_in(conn, ids)}
    attractions = load_attractions(conn, ids)
    city_of = {pid: p.city_slug for pid, p in places.items()}

    edges, edge_km, sources, estimated = [], {}, defaultdict(int), set()
    connected_pairs = set()
    for e in queries.list_edges(conn, ids):
        minutes = max(1, math.ceil(e["minutes"] * traffic_factor))
        edges.append((e["from_id"], e["to_id"], minutes))
        edge_km[(e["from_id"], e["to_id"])] = e["km"]
        sources[e["source"]] += 1
        if e["source"] == "haversine_estimate":
            estimated.add((e["from_id"], e["to_id"]))
        if e["scope"] == "intercity":
            connected_pairs.add(frozenset((city_of[e["from_id"]], city_of[e["to_id"]])))

    # Two selected cities with no road link between them in our data are joined by a
    # clearly labelled straight-line estimate between their hubs -- never by a zero.
    estimated_links = []
    for a, b in itertools.combinations([c["slug"] for c in rows], 2):
        if frozenset((a, b)) in connected_pairs:
            continue
        hub_a, hub_b = _hub(a, places), _hub(b, places)
        if hub_a is None or hub_b is None:
            continue
        straight = haversine_km(hub_a.lat, hub_a.lng, hub_b.lat, hub_b.lng)
        road_km = round(straight * config.ESTIMATE_DETOUR_FACTOR, 1)
        minutes = max(1, math.ceil(road_km / config.ESTIMATE_SPEED_KMH * 60))
        for u, v in ((hub_a.id, hub_b.id), (hub_b.id, hub_a.id)):
            edges.append((u, v, minutes))
            edge_km[(u, v)] = road_km
            estimated.add((u, v))
            sources["haversine_estimate"] += 1
        estimated_links.append((a, b, round(straight, 1)))

    graph = build_graph(places.keys(), edges)                 # adjacency list
    dist, prev = all_pairs_shortest_paths(graph)              # Dijkstra from every place
    plan = {u: {v: round_up_travel(d) for v, d in row.items()} for u, row in dist.items()}

    km = {}
    for u in graph:
        km[u] = {}
        for v in graph:
            path = reconstruct_path(prev[u], u, v)
            if not path:
                km[u][v] = math.inf
            else:
                km[u][v] = sum(edge_km[(a, b)] for a, b in zip(path, path[1:]))

    data = CityData(
        slug="+".join(c["slug"] for c in rows),
        name=group_name([c["name"] for c in rows]),
        state=base["state"], info=base, cities=rows,
        places=places, attractions=attractions,
        start_points=[p for p in places.values() if p.kind == "start" and p.city_slug == base["slug"]],
        graph=graph, edge_km=edge_km, edge_sources=dict(sources), estimated_edges=estimated,
        dist=dist, plan=plan, prev=prev, km=km, traffic_factor=traffic_factor,
        city_of=city_of, estimated_links=estimated_links,
        categories={c["slug"]: dict(c) for c in queries.list_categories(conn)},
        data_version=queries.get_meta(conn).get("dataset_fingerprint", ""),
        build_ms=(time.perf_counter() - started) * 1000,
    )
    data.by_slug = {p.slug: p for p in places.values()}
    return data


def load_city(conn, slug, traffic_factor=1.0):
    """Build a CityData for one city, or return None if the city does not exist."""
    return load_area(conn, [slug], traffic_factor)


def group_name(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " & " + names[-1]


# ----------------------------------------------------------------------------- cache

_CACHE = {}


def get_city_data(conn, db_path, slug, traffic_factor, extra=()):
    """Cached load_area. The key includes the DB file's modification time, so
    rebuilding the database automatically invalidates the cache."""
    try:
        stamp = os.path.getmtime(db_path)
    except OSError:
        stamp = None
    slugs = (slug,) + tuple(extra)
    key = (db_path, stamp, slugs, traffic_factor)
    if key not in _CACHE:
        data = load_area(conn, list(slugs), traffic_factor)
        if data is None:
            return None
        _CACHE[key] = data
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()
