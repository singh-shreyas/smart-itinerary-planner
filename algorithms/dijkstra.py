"""Dijkstra's shortest-path algorithm with a binary-heap priority queue.

Role in the project: we store only *local* road links (each place to its
nearest neighbours). Dijkstra chains those links together to find the shortest
travel time between every pair of places. A pair with no path keeps distance
math.inf, and the planner never routes between such places.

Complexity (V nodes, E edges):
    one source:   O((V + E) log V) time, O(V) space
    all pairs:    O(V (V + E) log V) time, O(V^2) space for the table
"""

import heapq
import math


def dijkstra(graph, source):
    """Shortest distances from `source` to every node.

    Returns (dist, prev):
        dist[v] = length of the shortest path source -> v (math.inf if unreachable)
        prev[v] = the node before v on that path (None for the source / unreachable)
    """
    if source not in graph:
        raise KeyError(f"unknown source node {source}")

    dist = {node: math.inf for node in graph}
    prev = {node: None for node in graph}
    dist[source] = 0

    heap = [(0, source)]                  # min-heap ordered by tentative distance
    while heap:
        d, u = heapq.heappop(heap)        # closest node not yet finalised
        if d > dist[u]:
            continue                      # stale entry: u was already settled with a shorter distance
        for v, weight in graph[u]:        # relax every outgoing edge of u
            new_distance = d + weight
            if new_distance < dist[v]:
                dist[v] = new_distance
                prev[v] = u
                heapq.heappush(heap, (new_distance, v))
    return dist, prev


def all_pairs_shortest_paths(graph):
    """Run Dijkstra from every node.

    Returns (dist, prev) where dist[s][t] is the shortest distance s -> t and
    prev[s] is the predecessor map of the run from s.
    """
    dist, prev = {}, {}
    for source in graph:
        dist[source], prev[source] = dijkstra(graph, source)
    return dist, prev


def reconstruct_path(prev, source, target):
    """Rebuild the node list source -> ... -> target from a predecessor map.

    Returns [] when target is unreachable.
    """
    if source == target:
        return [source]
    if prev.get(target) is None:
        return []
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path
