"""Dynamic programming: 0/1 knapsack over two resources (time and money).

Problem: choose a subset of attractions maximising total score such that
    sum(weight) <= T   (time units available in the day)
    sum(cost)   <= M   (money units in the daily budget)

Table:
    best[i][t][m] = best total score using only the first i items,
                    with at most t time units and m money units.

Recurrence (item i has weight w, cost c, score s):
    best[i][t][m] = best[i-1][t][m]                               (skip item i)
    best[i][t][m] = max(that, s + best[i-1][t-w][m-c])  if w <= t and c <= m   (take it)

The answer is best[n][T][M]; we walk the table backwards to recover which
items were taken. With no budget, M = 0 and every cost is 0, so this is exactly
the classic 1-D knapsack.

Complexity: O(n * T * M) time and space. This is *pseudo-polynomial*: it grows
with the numeric capacities T and M, not just with n. We keep T and M small by
working in 10-minute and Rs-unit blocks (see config.py).

Optimal for this knapsack model. It is NOT a claim that the whole itinerary is
optimal: the real problem (orienteering with time windows) is NP-hard.
"""

from algorithms.knapsack_types import summarise


def dp_select(items, time_cap, money_cap=None):
    """Optimal 0/1 knapsack selection over (time, money).

    items:     list of Item(id, score, weight, cost) with integer weight / cost
    time_cap:  integer time capacity T
    money_cap: integer money capacity M, or None to ignore cost

    Returns a SelectionResult for an optimal set.
    """
    n = len(items)
    T = max(time_cap, 0)
    use_money = money_cap is not None
    M = max(money_cap, 0) if use_money else 0

    def cost_of(item):
        return item.cost if use_money else 0

    # best[i][t][m], with row 0 meaning "no items considered yet" (all zeros).
    best = [[[0] * (M + 1) for _ in range(T + 1)] for _ in range(n + 1)]

    for i in range(1, n + 1):
        item = items[i - 1]
        w, c, s = item.weight, cost_of(item), item.score
        previous, current = best[i - 1], best[i]
        for t in range(T + 1):
            for m in range(M + 1):
                skip = previous[t][m]
                if w <= t and c <= m:
                    take = s + previous[t - w][m - c]
                    current[t][m] = take if take > skip else skip
                else:
                    current[t][m] = skip

    # Traceback: if the value changed between row i-1 and row i, item i was taken.
    chosen = []
    t, m = T, M
    for i in range(n, 0, -1):
        if best[i][t][m] != best[i - 1][t][m]:
            item = items[i - 1]
            chosen.append(item.id)
            t -= item.weight
            m -= cost_of(item)
    chosen.reverse()
    return summarise(items, chosen)


def brute_force_select(items, time_cap, money_cap=None):
    """Try every subset (2^n). Only for testing the DP on small inputs."""
    best_ids, best_score = [], -1
    n = len(items)
    for mask in range(1 << n):
        picked = [items[i] for i in range(n) if mask & (1 << i)]
        if sum(it.weight for it in picked) > time_cap:
            continue
        if money_cap is not None and sum(it.cost for it in picked) > money_cap:
            continue
        score = sum(it.score for it in picked)
        if score > best_score:
            best_ids, best_score = [it.id for it in picked], score
    return summarise(items, best_ids)
