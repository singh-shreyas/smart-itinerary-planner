# Algorithm Code (standalone)

Short, self-contained versions of the 14 algorithms described in the
[Algorithms Handbook](../algorithms-handbook.pdf), numbered in the order the handbook presents them.
Each file has a small built-in example and runs on its own. The versions the app actually uses live in
[`algorithms/`](../../algorithms/).

```bash
python3 python/02_dijkstra.py
cc -std=c99 c/02_dijkstra.c -o dijkstra && ./dijkstra
```

| # | Algorithm | Python | C |
|---|---|---|---|
| 01 | Weighted graph (adjacency list) | [01_graph.py](python/01_graph.py) | [01_graph.c](c/01_graph.c) |
| 02 | Dijkstra's shortest paths | [02_dijkstra.py](python/02_dijkstra.py) | [02_dijkstra.c](c/02_dijkstra.c) |
| 03 | Merge sort | [03_merge_sort.py](python/03_merge_sort.py) | [03_merge_sort.c](c/03_merge_sort.c) |
| 04 | Attraction scoring | [04_scoring.py](python/04_scoring.py) | [04_scoring.c](c/04_scoring.c) |
| 05 | Greedy selection | [05_greedy.py](python/05_greedy.py) | [05_greedy.c](c/05_greedy.c) |
| 06 | 0/1 knapsack (dynamic programming) | [06_knapsack_dp.py](python/06_knapsack_dp.py) | [06_knapsack_dp.c](c/06_knapsack_dp.c) |
| 07 | Tour cost | [07_tour_cost.py](python/07_tour_cost.py) | [07_tour_cost.c](c/07_tour_cost.c) |
| 08 | Nearest-neighbour tour | [08_nearest_neighbour.py](python/08_nearest_neighbour.py) | [08_nearest_neighbour.c](c/08_nearest_neighbour.c) |
| 09 | 2-opt improvement | [09_two_opt.py](python/09_two_opt.py) | [09_two_opt.c](c/09_two_opt.c) |
| 10 | Activity selection | [10_activity_selection.py](python/10_activity_selection.py) | [10_activity_selection.c](c/10_activity_selection.c) |
| 11 | Cheapest insertion | [11_insertion.py](python/11_insertion.py) | [11_insertion.c](c/11_insertion.c) |
| 12 | Held–Karp (exact tour) | [12_held_karp.py](python/12_held_karp.py) | [12_held_karp.c](c/12_held_karp.c) |
| 13 | Min-heap repair | [13_min_heap_repair.py](python/13_min_heap_repair.py) | [13_min_heap_repair.c](c/13_min_heap_repair.c) |
| 14 | Day partition | [14_day_partition.py](python/14_day_partition.py) | [14_day_partition.c](c/14_day_partition.c) |
