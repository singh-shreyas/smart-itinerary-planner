"""Held-Karp: exact shortest tour by dynamic programming over subsets (bitmasks).

Used ONLY on the comparison page, to measure how far Nearest Neighbour and
2-opt are from the true optimum for a day's stops. It ignores opening hours,
so it is a lower bound on the travel of any feasible order of those stops.

State: dp[mask][j] = cheapest way to leave the start, visit exactly the set of
stops in `mask`, and stand at stop j.
    dp[{j}][j]          = t(start, j)
    dp[mask | {k}][k]   = min over j in mask of dp[mask][j] + t(j, k)
    answer              = min over j of dp[all][j] + t(j, start)

Complexity: O(2^k * k^2) time, O(2^k * k) space -- fine for k <= ~12.
"""

import math


def held_karp(start, stops, dist):
    """Return (optimal_cost, optimal_order) for the closed tour over `stops`."""
    k = len(stops)
    if k == 0:
        return 0, []

    full = (1 << k) - 1
    dp = [[math.inf] * k for _ in range(1 << k)]
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
                    dp[new_mask][nxt] = cost
                    parent[new_mask][nxt] = j

    best_cost, last = math.inf, -1
    for j in range(k):
        cost = dp[full][j] + dist[stops[j]][start]
        if cost < best_cost:
            best_cost, last = cost, j
    if last == -1:
        return math.inf, []

    # Walk the parent pointers back to recover the order.
    order, mask = [], full
    while last != -1:
        order.append(stops[last])
        previous = parent[mask][last]
        mask ^= 1 << last
        last = previous
    order.reverse()
    return best_cost, order
