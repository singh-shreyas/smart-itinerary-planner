# Dijkstra with a binary min-heap, plus all-pairs and path rebuild (as in algorithms/dijkstra.py)
import heapq
import math


def dijkstra(graph, source):
    dist = {node: math.inf for node in graph}
    prev = {node: None for node in graph}
    dist[source] = 0
    heap = [(0, source)]                       # (tentative distance, node)
    while heap:
        d, u = heapq.heappop(heap)             # closest unsettled node
        if d > dist[u]:
            continue                           # stale entry (lazy deletion)
        for v, weight in graph[u]:             # relax every edge out of u
            nd = d + weight
            if nd < dist[v]:
                dist[v], prev[v] = nd, u
                heapq.heappush(heap, (nd, v))
    return dist, prev


def all_pairs_shortest_paths(graph):
    dist, prev = {}, {}
    for source in graph:
        dist[source], prev[source] = dijkstra(graph, source)
    return dist, prev


def reconstruct_path(prev, source, target):
    if source == target:
        return [source]
    if prev.get(target) is None:
        return []                              # unreachable
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    return path[::-1]


if __name__ == "__main__":
    graph = {"A": [("B", 10), ("C", 20)], "B": [("A", 10), ("C", 5)],
             "C": [("A", 20), ("B", 5), ("D", 15)], "D": [("C", 15)]}
    dist, prev = all_pairs_shortest_paths(graph)
    for s in graph:
        print(s, [dist[s][t] for t in graph])
    print("path A->D:", reconstruct_path(prev["A"], "A", "D"))
