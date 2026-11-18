# Cost of a closed tour on a directed distance table (as in algorithms/tour.py)
DIST = [[0, 12, 20, 25, 15],
        [11, 0, 9, 18, 22],
        [21, 8, 0, 7, 16],
        [24, 19, 6, 0, 10],
        [14, 23, 17, 9, 0]]


def tour_cost(start, route, dist, closed=True):
    if not route:
        return 0
    total = dist[start][route[0]]
    for a, b in zip(route, route[1:]):
        total += dist[a][b]
    if closed:
        total += dist[route[-1]][start]
    return total


if __name__ == "__main__":
    print(tour_cost(0, [1, 2, 3, 4], DIST))   # 0->1->2->3->4->0
    print(tour_cost(0, [4, 3, 2, 1], DIST))   # same stops, reversed: different, the table is directed
