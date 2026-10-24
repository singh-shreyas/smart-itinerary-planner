"""Cross-check our Dijkstra against NetworkX on the same graph.

NetworkX is used ONLY here, as an independent reference implementation. The
planner never uses it. Equal distances on every ordered pair of places is
strong evidence our implementation is correct.
"""

import math

import networkx as nx

from algorithms.dijkstra import all_pairs_shortest_paths
from services.timing import median_ms


def to_networkx(graph):
    """Same graph as a NetworkX DiGraph. A DiGraph holds one edge per (u, v), and
    add_edge would silently overwrite, so parallel edges keep their minimum weight,
    which is the one any shortest path would use."""
    g = nx.DiGraph()
    g.add_nodes_from(graph)
    for u, neighbours in graph.items():
        for v, weight in neighbours:
            if not g.has_edge(u, v) or weight < g[u][v]["weight"]:
                g.add_edge(u, v, weight=weight)
    return g


def compare_all_pairs(graph, ours=None):
    """Compare every pair. Returns counts and the largest absolute difference."""
    if ours is None:
        ours, _ = all_pairs_shortest_paths(graph)
    theirs = dict(nx.all_pairs_dijkstra_path_length(to_networkx(graph), weight="weight"))
    pairs = mismatches = 0
    largest = 0.0
    for u in graph:
        for v in graph:
            pairs += 1
            a = ours[u][v]
            b = theirs.get(u, {}).get(v, math.inf)
            if a == math.inf and b == math.inf:
                continue
            if a == math.inf or b == math.inf or abs(a - b) > 1e-9:
                mismatches += 1
                largest = math.inf if (a == math.inf) != (b == math.inf) else max(largest, abs(a - b))
    return {"pairs": pairs, "mismatches": mismatches, "largest_difference": largest}


def crosscheck_city(city, repeats=5):
    """Correctness check plus (clearly secondary) timing of both implementations."""
    result = compare_all_pairs(city.graph, city.dist)
    g = to_networkx(city.graph)
    result.update(
        vertices=city.vertex_count,
        edges=city.edge_count,
        ours_ms=median_ms(lambda: all_pairs_shortest_paths(city.graph), repeats),
        networkx_ms=median_ms(lambda: dict(nx.all_pairs_dijkstra_path_length(g, weight="weight")), repeats),
    )
    return result
