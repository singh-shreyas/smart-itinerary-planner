"""Greedy attraction selection (fast baseline).

Idea: sort attractions by "value per unit of resource" and take each one that
still fits. With only a time limit the density is score / weight. With a budget
too, each item uses a fraction of both limits, so

    density = score / (weight / time_cap + cost / money_cap)

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


def greedy_select(items, time_cap, money_cap=None):
    """Choose items greedily by density.

    items:     list of Item(id, score, weight, cost) with integer weight / cost
    time_cap:  integer capacity in time units
    money_cap: integer capacity in money units, or None for "no budget"

    Returns a SelectionResult. Time: O(n log n) for the sort + O(n) scan.
    """
    if time_cap <= 0 or not items:
        return summarise(items, [])
    use_money = money_cap is not None and money_cap > 0

    def density(item):
        resource = item.weight / time_cap
        if use_money:
            resource += item.cost / money_cap
        return item.score / resource if resource > 0 else float("inf")

    # Highest density first; ties broken by smaller id so the result is deterministic.
    ordered = merge_sort(items, key=lambda it: (-density(it), it.id))

    chosen, used_time, used_money = [], 0, 0
    for item in ordered:
        fits_time = used_time + item.weight <= time_cap
        fits_money = money_cap is None or used_money + item.cost <= money_cap
        if fits_time and fits_money:
            chosen.append(item.id)
            used_time += item.weight
            used_money += item.cost
    return summarise(items, chosen)
