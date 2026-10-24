"""Our own implementations of the ADA algorithms used by the planner.

Rule for this package: nothing here imports Flask, sqlite3 or the services
layer. Every function works on plain lists, dicts and numbers, which is what
lets each algorithm be unit-tested (and explained) on its own.

    graph.py               weighted directed graph as an adjacency list
    dijkstra.py            single-source and all-pairs shortest paths (binary heap)
    sorting.py             merge sort (our sorting step) + score ranking
    scoring.py             the attraction value score
    knapsack_types.py      Item / SelectionResult shared by the two selectors
    greedy.py              greedy knapsack-style selection
    dynamic_programming.py 0/1 knapsack over (time, money) with traceback
    nearest_neighbor.py    nearest-neighbour route construction
    two_opt.py             2-opt local search (directed costs, optional feasibility check)
    activity_selection.py  classic activity selection + earliest-deadline ordering
    insertion.py           deadline-order cheapest feasible insertion (window-first route)
    held_karp.py           exact bitmask DP tour, used only for comparison
    tour.py                cost of a closed tour (shared helper)
"""
