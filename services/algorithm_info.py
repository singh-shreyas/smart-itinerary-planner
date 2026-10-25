"""Descriptions of every algorithm, shown on the landing and About pages.

Kept in one place so the UI and the viva notes never disagree.
"""

ALGORITHMS = [
    {
        "key": "graph", "name": "Graph (adjacency list)", "icon": "bi-diagram-3",
        "file": "algorithms/graph.py", "time": "O(V + E)", "space": "O(V + E)", "role": "Main plan",
        "summary": "Every place is a node; each place stores directed road links to its 5 nearest "
                   "neighbours, with travel minutes as weights.",
    },
    {
        "key": "dijkstra", "name": "Dijkstra's shortest paths", "icon": "bi-signpost-split",
        "file": "algorithms/dijkstra.py", "time": "O(V (V + E) log V) all pairs", "space": "O(V²) table",
        "role": "Main plan",
        "summary": "Runs from every place with a binary heap to chain local links into the shortest travel "
                   "time between any two places. Cross-checked against NetworkX.",
    },
    {
        "key": "sorting", "name": "Sorting & priority queues", "icon": "bi-sort-down",
        "file": "algorithms/sorting.py", "time": "O(n log n) / O(log n)", "space": "O(n)", "role": "Main plan",
        "summary": "Our merge sort orders candidates by score or closing time; binary heaps drive Dijkstra "
                   "and pick the weakest stop during repair.",
    },
    {
        "key": "greedy", "name": "Greedy selection", "icon": "bi-lightning-charge",
        "file": "algorithms/greedy.py", "time": "O(n log n)", "space": "O(n)", "role": "Strategy / baseline",
        "summary": "Takes attractions in order of value per minute of the day while they still fit. "
                   "Fast, but can miss the best combination.",
    },
    {
        "key": "dp", "name": "Dynamic programming (0/1 knapsack)", "icon": "bi-grid-3x3",
        "file": "algorithms/dynamic_programming.py", "time": "O(n · T)", "space": "O(n · T)",
        "role": "Default strategy",
        "summary": "A 0/1 knapsack over the day's available minutes that finds the highest-value set "
                   "of attractions for the day's estimated capacity.",
    },
    {
        "key": "max_visits", "name": "Max visits (DP on the count)", "icon": "bi-list-ol",
        "file": "algorithms/max_visits.py", "time": "O(n · T)", "space": "O(n · T)",
        "role": "Strategy",
        "summary": "The same knapsack DP with every place worth one visit (ties broken by value), so it "
                   "finds the largest number of places that fit the day's time.",
    },
    {
        "key": "nn", "name": "Nearest Neighbour", "icon": "bi-geo-alt",
        "file": "algorithms/nearest_neighbor.py", "time": "O(k²)", "space": "O(k)", "role": "Main plan",
        "summary": "Builds a first route by always travelling to the closest unvisited stop.",
    },
    {
        "key": "two_opt", "name": "2-opt local search", "icon": "bi-bezier2",
        "file": "algorithms/two_opt.py", "time": "O(k³) per pass", "space": "O(k)", "role": "Main plan",
        "summary": "Reverses route segments while that shortens the tour (and keeps every opening window "
                   "satisfied). Gives a local, not guaranteed global, optimum.",
    },
    {
        "key": "activity", "name": "Activity selection", "icon": "bi-calendar-week",
        "file": "algorithms/activity_selection.py", "time": "O(n log n)", "space": "O(n)",
        "role": "Main plan / baseline",
        "summary": "Earliest-closing-time-first ordering decides which stop the window-first route "
                   "considers next, so places that close early are placed first.",
    },
    {
        "key": "insertion", "name": "Feasible insertion", "icon": "bi-node-plus",
        "file": "algorithms/insertion.py", "time": "O(k³)", "space": "O(k)", "role": "Main plan",
        "summary": "Places a stop at the position that keeps every opening window and meal valid with the "
                   "least extra travel. Builds the window-first route and fills leftover time in long days.",
    },
    {
        "key": "held_karp", "name": "Held–Karp (exact tour)", "icon": "bi-bullseye",
        "file": "algorithms/held_karp.py", "time": "O(2ᵏ · k²)", "space": "O(2ᵏ · k)", "role": "Comparison only",
        "summary": "Bitmask DP that finds the truly shortest tour for a day's stops, so we can measure how "
                   "far Nearest Neighbour and 2-opt are from optimal.",
    },
]
