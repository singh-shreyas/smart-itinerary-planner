# 2-opt local search with directed costs (as in algorithms/two_opt.py)
DIST = [[0, 12, 20, 25, 15],
        [11, 0, 9, 18, 22],
        [21, 8, 0, 7, 16],
        [24, 19, 6, 0, 10],
        [14, 23, 17, 9, 0]]


def tour_cost(start, route, dist):
    if not route:
        return 0
    legs = [start] + route + [start]
    return sum(dist[a][b] for a, b in zip(legs, legs[1:]))


def two_opt(start, route, dist, is_feasible=None):
    best = list(route)
    best_cost = tour_cost(start, best, dist)
    n = len(best)
    improved = True
    while improved:                                  # one pass = every pair (i, j)
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]   # reverse i..j
                cost = tour_cost(start, candidate, dist)                   # full re-cost: directed
                if cost < best_cost - 1e-9:
                    if is_feasible is not None and not is_feasible(candidate):
                        continue
                    best, best_cost, improved = candidate, cost, True
    return best, best_cost


if __name__ == "__main__":
    start_route = [4, 3, 1, 2]
    print("before:", start_route, tour_cost(0, start_route, DIST))
    print("after: ", *two_opt(0, start_route, DIST))
