# 0/1 knapsack over the day's time, with traceback (as in algorithms/dynamic_programming.py)
from collections import namedtuple

Item = namedtuple("Item", "id score weight")


def dp_select(items, time_cap):
    n, T = len(items), max(time_cap, 0)
    best = [[0] * (T + 1) for _ in range(n + 1)]   # best[i][t]: first i items, at most t units
    for i in range(1, n + 1):
        w, s = items[i - 1].weight, items[i - 1].score
        for t in range(T + 1):
            skip = best[i - 1][t]
            take = s + best[i - 1][t - w] if w <= t else -1
            best[i][t] = max(skip, take)
    chosen, t = [], T                              # walk back: a changed value means "taken"
    for i in range(n, 0, -1):
        if best[i][t] != best[i - 1][t]:
            chosen.append(items[i - 1].id)
            t -= items[i - 1].weight
    return chosen[::-1], best[n][T]


if __name__ == "__main__":
    items = [Item("X", 90, 18), Item("Y", 60, 15), Item("Z", 60, 15)]
    print(dp_select(items, 30))
    print(dp_select([Item("A", 90, 3), Item("B", 50, 2), Item("C", 50, 2)], 4))   # slide 5 dry run
