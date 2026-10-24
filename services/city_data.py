"""Load one city from SQLite and prepare everything the planner needs.

Done once per city and cached in memory:
    1. load places, attractions, opening hours and road links from SQLite
    2. build the adjacency list (graph.py)
    3. run Dijkstra from every place (dijkstra.py) -> travel-time table + paths

Edge minutes in the database are free-flow OSRM times. Here they are multiplied
by the configured traffic factor and rounded UP to whole minutes, so every
travel time in the planner is an integer and timelines add up exactly.
"""

import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

from algorithms.dijkstra import all_pairs_shortest_paths, reconstruct_path
from algorithms.graph import build_graph, edge_count
from database import queries
from services.models import Attraction, Leg, Place, Window


@dataclass
class CityData:
    slug: str
    name: str
    state: str
    info: dict
    places: dict                      # place id -> Place (attractions and start points)
    attractions: dict                 # place id -> Attraction
    start_points: list                # [Place]
    graph: dict                       # adjacency list: id -> [(neighbour id, minutes)]
    edge_km: dict                     # (u, v) -> road km of that direct link
    edge_sources: dict                # source name -> number of links
    dist: dict                        # dist[u][v] = shortest minutes (math.inf if no path)
    prev: dict                        # prev[u] = Dijkstra predecessor map from u
    km: dict                          # km[u][v] = road km along that shortest path
    traffic_factor: float
    build_ms: float = 0.0
    by_slug: dict = field(default_factory=dict)

    @property
    def vertex_count(self):
        return len(self.graph)

    @property
    def edge_count(self):
        return edge_count(self.graph)

    def place(self, slug):
        return self.by_slug.get(slug)

    def attraction_by_slug(self, slug):
        place = self.by_slug.get(slug)
        return self.attractions.get(place.id) if place else None

    def path(self, u, v):
        return reconstruct_path(self.prev[u], u, v)

    def leg(self, u, v):
        """Travel u -> v along Dijkstra's shortest path."""
        path = self.path(u, v)
        via = [self.places[node].name for node in path[1:-1]]
        return Leg(from_id=u, to_id=v, minutes=self.dist[u][v], km=round(self.km[u][v], 2), via=via)


def _attractions_from_rows(rows, hour_rows):
    hours = defaultdict(lambda: defaultdict(list))
    for h in hour_rows:
        hours[h["place_id"]][h["weekday"]].append(Window(h["open_min"], h["close_min"], h["last_entry_min"]))
    attractions = {}
    for r in rows:
        weekly = {day: sorted(ws, key=lambda w: w.open_min) for day, ws in hours[r["id"]].items()}
        attractions[r["id"]] = Attraction(
            id=r["id"], slug=r["slug"], name=r["name"], lat=r["lat"], lng=r["lng"],
            rating=r["rating"], popularity=r["popularity"], visit_min=r["visit_minutes"], fee=r["fee_inr"],
            categories=tuple(sorted((r["category_slugs"] or "").split(","))) if r["category_slugs"] else (),
            hours=weekly, description=r["description"], image=r["image_path"],
            image_credit=r["image_credit"], image_source_url=r["image_source_url"], info_url=r["info_url"],
            data_status=r["data_status"], in_team_catalog=bool(r["in_team_catalog"]),
            city_slug=r["city_slug"], city_name=r["city_name"],
        )
    return attractions


def load_attractions(conn, city_id=None):
    """Attraction objects (with weekly hours) for one city, or for all cities."""
    return _attractions_from_rows(queries.list_attractions(conn, city_id),
                                  queries.list_opening_hours(conn, city_id))


def load_city(conn, slug, traffic_factor=1.0):
    """Build a CityData for `slug`, or return None if the city does not exist."""
    city = queries.get_city(conn, slug)
    if city is None:
        return None
    started = time.perf_counter()

    places = {r["id"]: Place(r["id"], r["slug"], r["name"], r["kind"], r["lat"], r["lng"])
              for r in queries.list_places(conn, city["id"])}
    attractions = load_attractions(conn, city["id"])

    edges, edge_km, sources = [], {}, defaultdict(int)
    for e in queries.list_edges(conn, city["id"]):
        minutes = max(1, math.ceil(e["minutes"] * traffic_factor))
        edges.append((e["from_id"], e["to_id"], minutes))
        edge_km[(e["from_id"], e["to_id"])] = e["km"]
        sources[e["source"]] += 1

    graph = build_graph(places.keys(), edges)                 # adjacency list
    dist, prev = all_pairs_shortest_paths(graph)              # Dijkstra from every place

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
        slug=city["slug"], name=city["name"], state=city["state"], info=dict(city),
        places=places, attractions=attractions,
        start_points=[p for p in places.values() if p.kind == "start"],
        graph=graph, edge_km=edge_km, edge_sources=dict(sources),
        dist=dist, prev=prev, km=km, traffic_factor=traffic_factor,
        build_ms=(time.perf_counter() - started) * 1000,
    )
    data.by_slug = {p.slug: p for p in places.values()}
    return data


# ----------------------------------------------------------------------------- cache

_CACHE = {}


def get_city_data(conn, db_path, slug, traffic_factor):
    """Cached load_city. The key includes the DB file's modification time, so
    rebuilding the database automatically invalidates the cache."""
    try:
        stamp = os.path.getmtime(db_path)
    except OSError:
        stamp = None
    key = (db_path, stamp, slug, traffic_factor)
    if key not in _CACHE:
        data = load_city(conn, slug, traffic_factor)
        if data is None:
            return None
        _CACHE[key] = data
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()
