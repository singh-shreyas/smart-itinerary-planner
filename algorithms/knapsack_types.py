"""Small shared types for the two selection algorithms (Greedy and DP).

Both selectors receive the *same* integer instance: weights are already in
time units (10-minute blocks) and costs in money units, so comparing them is
fair. The services layer does the rounding; these algorithms only see integers.
"""

from collections import namedtuple

# id: attraction id, score: integer value, weight: time units, cost: money units
Item = namedtuple("Item", "id score weight cost")

# chosen: list of item ids (in input order), plus the totals of the chosen set
SelectionResult = namedtuple("SelectionResult", "chosen score weight cost")


def summarise(items, chosen_ids):
    """Build a SelectionResult for a set of chosen ids."""
    chosen_set = set(chosen_ids)
    picked = [it for it in items if it.id in chosen_set]
    return SelectionResult(
        chosen=[it.id for it in picked],
        score=sum(it.score for it in picked),
        weight=sum(it.weight for it in picked),
        cost=sum(it.cost for it in picked),
    )
