# Nearest Neighbour route construction (as in algorithms/nearest_neighbor.py)
import math

DIST = [[0, 12, 20, 25, 15],
        [11, 0, 9, 18, 22],
        [21, 8, 0, 7, 16],
        [24, 19, 6, 0, 10],
        [14, 23, 17, 9, 0]]


def nearest_neighbor_route(start, stops, dist):
    remaining, route, current = set(stops), [], start
    while remaining:
        nearest = min(remaining, key=lambda s: (dist[current][s], s))   # ties -> smaller id
        if dist[current][nearest] == math.inf:
            route.extend(sorted(remaining))        # nothing reachable: append the rest
            break
        route.append(nearest)
        remaining.remove(nearest)
        current = nearest
    return route


if __name__ == "__main__":
    print(nearest_neighbor_route(0, [1, 2, 3, 4], DIST))
