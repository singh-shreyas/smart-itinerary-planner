"""Maximum visits: the most places that fit, via the same 0/1 knapsack DP.

Objective: maximise the NUMBER of chosen items subject to the same time and
money capacities as the value-maximising DP. Among sets of equal size, prefer
the one with the higher total score (a deterministic, sensible tie-break).

Trick (lexicographic objective): give every item the value

    v_i = B + score_i      with  B = (sum of all scores) + 1

Any set with one more item gains at least B, which is more than the largest
possible difference in total score between two sets. So the DP's optimum has
the maximum count first, and the maximum total score among those second.

Why not "sort by duration and take the shortest"? With a single time limit
that greedy rule is optimal for the count, but with time AND money limits it is
not (a short but expensive place can block two cheap ones). The DP handles both
constraints exactly -- for the knapsack model, like dp_select.

Complexity: identical to dp_select, O(n * T * M).
"""

from algorithms.dynamic_programming import dp_select
from algorithms.knapsack_types import summarise


def count_first_values(items):
    """Items re-valued so that maximising value maximises count first, then score."""
    big = sum(max(item.score, 0) for item in items) + 1
    return [item._replace(score=big + item.score) for item in items]


def max_visits_select(items, time_cap, money_cap=None):
    """Most items that fit (ties: highest total score). Totals are reported in ORIGINAL scores."""
    result = dp_select(count_first_values(items), time_cap, money_cap)
    return summarise(items, result.chosen)
