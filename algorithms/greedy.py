"""Greedy attraction selection (fast baseline).

Idea: sort attractions by "value per unit of time" and take each one that
still fits:

    density = score / weight

Greedy is fast, O(n log n), but NOT optimal for the 0/1 knapsack. The classic
counter-example ("greedy trap"), capacity 300 minutes:
    X: 180 min, score 90  (0.50 per min)  <- greedy takes this first
    Y: 150 min, score 60  (0.40 per min)
    Z: 150 min, score 60  (0.40 per min)
Greedy takes X and then neither Y nor Z fits: total 90.
The optimum is Y + Z: total 120. Our DP finds it.
"""

from algorithms.knapsack_types import summarise
from algorithms.sorting import merge_sort


def greedy_select(items, time_cap):
    """Choose items greedily by density.

    items:    list of Item(id, score, weight) with integer weight
    time_cap: integer capacity in time units

    Returns a SelectionResult. Time: O(n log n) for the sort + O(n) scan.
    """
    if time_cap <= 0 or not items:
        return summarise(items, [])

    def density(item):
        return item.score / item.weight if item.weight > 0 else float("inf")

    # Highest density first; ties broken by smaller id so the result is deterministic.
    ordered = merge_sort(items, key=lambda it: (-density(it), it.id))

    chosen, used_time = [], 0
    for item in ordered:
        if used_time + item.weight <= time_cap:
            chosen.append(item.id)
            used_time += item.weight
    return summarise(items, chosen)
