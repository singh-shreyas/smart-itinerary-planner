"""Dynamic programming: 0/1 knapsack over the day's time.

Problem: choose a subset of attractions maximising total score such that
    sum(weight) <= T   (time units available in the day)

Table:
    best[i][t] = best total score using only the first i items,
                 with at most t time units.

Recurrence (item i has weight w, score s):
    best[i][t] = best[i-1][t]                                  (skip item i)
    best[i][t] = max(that, s + best[i-1][t-w])   if w <= t     (take it)

The answer is best[n][T]; we walk the table backwards to recover which
items were taken.

Complexity: O(n * T) time and space. This is *pseudo-polynomial*: it grows
with the numeric capacity T, not just with n. We keep T small by working in
10-minute blocks (see config.py).

Optimal for this knapsack model. It is NOT a claim that the whole itinerary is
optimal: the real problem (orienteering with time windows) is NP-hard.
"""

from algorithms.knapsack_types import summarise


def dp_select(items, time_cap):
    """Optimal 0/1 knapsack selection over time.

    items:    list of Item(id, score, weight) with integer weight
    time_cap: integer time capacity T

    Returns a SelectionResult for an optimal set.
    """
    n = len(items)
    T = max(time_cap, 0)

    # best[i][t], with row 0 meaning "no items considered yet" (all zeros).
    best = [[0] * (T + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        item = items[i - 1]
        w, s = item.weight, item.score
        previous, current = best[i - 1], best[i]
        for t in range(T + 1):
            skip = previous[t]
            if w <= t:
                take = s + previous[t - w]
                current[t] = take if take > skip else skip
            else:
                current[t] = skip

    # Traceback: if the value changed between row i-1 and row i, item i was taken.
    chosen = []
    t = T
    for i in range(n, 0, -1):
        if best[i][t] != best[i - 1][t]:
            item = items[i - 1]
            chosen.append(item.id)
            t -= item.weight
    chosen.reverse()
    return summarise(items, chosen)


def brute_force_select(items, time_cap):
    """Try every subset (2^n). Only for testing the DP on small inputs."""
    best_ids, best_score = [], -1
    n = len(items)
    for mask in range(1 << n):
        picked = [items[i] for i in range(n) if mask & (1 << i)]
        if sum(it.weight for it in picked) > time_cap:
            continue
        score = sum(it.score for it in picked)
        if score > best_score:
            best_ids, best_score = [it.id for it in picked], score
    return summarise(items, best_ids)
