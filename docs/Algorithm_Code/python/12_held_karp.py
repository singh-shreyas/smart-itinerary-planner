# Held-Karp: exact shortest closed tour by DP over subsets (as in algorithms/held_karp.py)
import math

DIST = [[0, 12, 20, 25, 15],
        [11, 0, 9, 18, 22],
        [21, 8, 0, 7, 16],
        [24, 19, 6, 0, 10],
        [14, 23, 17, 9, 0]]


def held_karp(start, stops, dist):
    k = len(stops)
    if k == 0:
        return 0, []
    full = (1 << k) - 1
    dp = [[math.inf] * k for _ in range(1 << k)]       # dp[mask][j]: visited mask, standing at j
    parent = [[-1] * k for _ in range(1 << k)]
    for j in range(k):
        dp[1 << j][j] = dist[start][stops[j]]
    for mask in range(1, full + 1):
        for j in range(k):
            if not mask & (1 << j) or dp[mask][j] == math.inf:
                continue
            for nxt in range(k):
                if mask & (1 << nxt):
                    continue
                new_mask = mask | (1 << nxt)
                cost = dp[mask][j] + dist[stops[j]][stops[nxt]]
                if cost < dp[new_mask][nxt]:
                    dp[new_mask][nxt], parent[new_mask][nxt] = cost, j
    best_cost, last = math.inf, -1
    for j in range(k):
        cost = dp[full][j] + dist[stops[j]][start]
        if cost < best_cost:
            best_cost, last = cost, j
    order, mask = [], full
    while last != -1:                                  # follow parent pointers back
        order.append(stops[last])
        previous = parent[mask][last]
        mask ^= 1 << last
        last = previous
    return best_cost, order[::-1]


if __name__ == "__main__":
    print(held_karp(0, [1, 2, 3, 4], DIST))
