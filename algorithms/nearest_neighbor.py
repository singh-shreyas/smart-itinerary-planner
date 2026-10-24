"""Nearest Neighbour heuristic for building a day's route.

Start at the hotel, repeatedly travel to the closest stop not yet visited, and
finally return to the hotel. Fast and simple, but greedy: an early short hop
can force a long trip later, so the route is usually not the shortest one.
That is why 2-opt is applied afterwards.

Complexity: O(k^2) for k stops (k choices, each scanning up to k candidates).
"""

import math


def nearest_neighbor_route(start, stops, dist):
    """Return the stops in nearest-neighbour order (start is not included).

    dist[a][b] is the shortest travel time a -> b (from Dijkstra).
    Ties are broken by the smaller stop id, so the result is deterministic.
    Stops that cannot be reached from the current position are appended at the
    end; the scheduler will then report that route as infeasible.
    """
    remaining = set(stops)
    route = []
    current = start
    while remaining:
        nearest = min(remaining, key=lambda s: (dist[current][s], s))
        if dist[current][nearest] == math.inf:
            # Nothing left is reachable from here; keep the rest in id order.
            route.extend(sorted(remaining))
            break
        route.append(nearest)
        remaining.remove(nearest)
        current = nearest
    return route
