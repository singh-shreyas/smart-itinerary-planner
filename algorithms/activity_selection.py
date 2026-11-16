"""Activity Selection and its use for opening-hours (time-window) routing.

1. Classic Activity Selection (as taught):
   Given fixed intervals [start, finish), choose the maximum number of
   non-overlapping ones. Greedy rule: sort by finish time and take every
   interval that starts after the last chosen one finishes. Optimal by the
   exchange argument. O(n log n) for the sort + O(n) scan.

2. In our planner the same "earliest finish first" idea orders a day's chosen
   stops by closing time (earliest_deadline_order), so places that close early
   are considered first when the window-first route is built (insertion.py).

Why (2) is only a heuristic: the textbook proof assumes fixed intervals with no
gaps between them. Our visits can start anywhere inside an opening window and
need travel time between places, so the optimality guarantee does not carry
over. (Selection therefore uses the knapsack algorithms instead.)
"""

from algorithms.sorting import merge_sort


def select_activities(intervals):
    """Classic activity selection.

    intervals: list of (id, start, finish)
    Returns the ids of a maximum-size set of mutually compatible intervals,
    in the order they happen.
    """
    by_finish = merge_sort(intervals, key=lambda x: (x[2], x[1], x[0]))
    chosen = []
    last_finish = float("-inf")
    for activity_id, start, finish in by_finish:
        if start >= last_finish:          # compatible with everything chosen so far
            chosen.append(activity_id)
            last_finish = finish
    return chosen


def earliest_deadline_order(stops, closing_time):
    """Order stops by closing time (earliest first), ties by stop id."""
    return merge_sort(stops, key=lambda s: (closing_time[s], s))
