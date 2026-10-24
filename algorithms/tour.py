"""Cost of a closed tour: start -> route[0] -> ... -> route[-1] -> start."""

import math


def tour_cost(start, route, dist, closed=True):
    """Total travel along the tour using the (directed) distance table.

    Returns math.inf if any leg has no path. O(k) for k stops.
    """
    if not route:
        return 0
    total = dist[start][route[0]]
    for a, b in zip(route, route[1:]):
        total += dist[a][b]
    if closed:
        total += dist[route[-1]][start]
    return total if total < math.inf else math.inf
