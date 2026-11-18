# Cheapest feasible insertion and the window-first route (as in algorithms/insertion.py).
# In the project, is_feasible is the minute-by-minute scheduler (services/scheduler.py).
# This demo uses a small stand-in: visits of fixed length that must end before closing time.
DIST = [[0, 12, 20, 25, 15],
        [11, 0, 9, 18, 22],
        [21, 8, 0, 7, 16],
        [24, 19, 6, 0, 10],
        [14, 23, 17, 9, 0]]
VISIT = {1: 60, 2: 90, 3: 45, 4: 60}                  # minutes on site
CLOSES = {1: 13 * 60, 2: 17 * 60, 3: 12 * 60, 4: 18 * 60}
DAY_START = 9 * 60


def tour_cost(start, route, dist):
    legs = [start] + route + [start]
    return sum(dist[a][b] for a, b in zip(legs, legs[1:]))


def is_feasible(route, start=0):
    clock, here = DAY_START, start
    for stop in route:
        clock += DIST[here][stop] + VISIT[stop]
        if clock > CLOSES[stop]:
            return False
        here = stop
    return True


def cheapest_feasible_insertion(start, route, stop, dist, feasible):
    best_cost, best_route = None, None
    for position in range(len(route) + 1):
        candidate = route[:position] + [stop] + route[position:]
        if not feasible(candidate):
            continue
        cost = tour_cost(start, candidate, dist)
        if best_cost is None or cost < best_cost:          # ties keep the earlier position
            best_cost, best_route = cost, candidate
    return best_route


def deadline_insertion_route(start, stops, closing_time, dist, feasible):
    route, unplaced = [], []
    for stop in sorted(stops, key=lambda s: (closing_time[s], s)):   # earliest closing first
        inserted = cheapest_feasible_insertion(start, route, stop, dist, feasible)
        if inserted is None:
            unplaced.append(stop)
        else:
            route = inserted
    return route, unplaced


if __name__ == "__main__":
    route, unplaced = deadline_insertion_route(0, [1, 2, 3, 4], CLOSES, DIST, is_feasible)
    print("route:", route, "travel:", tour_cost(0, route, DIST), "unplaced:", unplaced)
