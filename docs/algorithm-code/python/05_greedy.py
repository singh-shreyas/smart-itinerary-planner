# Greedy selection by value per time unit (as in algorithms/greedy.py)
from collections import namedtuple

Item = namedtuple("Item", "id score weight")        # weight in 10-minute units


def greedy_select(items, time_cap):
    if time_cap <= 0 or not items:
        return [], 0
    density = lambda it: it.score / it.weight if it.weight > 0 else float("inf")
    ordered = sorted(items, key=lambda it: (-density(it), it.id))   # the project uses its own merge sort here
    chosen, used = [], 0
    for item in ordered:
        if used + item.weight <= time_cap:
            chosen.append(item.id)
            used += item.weight
    return sorted(chosen), sum(it.score for it in items if it.id in chosen)


if __name__ == "__main__":
    # the "greedy trap": X 180 min, Y and Z 150 min each, a 300-minute day
    items = [Item("X", 90, 18), Item("Y", 60, 15), Item("Z", 60, 15)]
    print(greedy_select(items, 30))
