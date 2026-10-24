"""Sorting: our own merge sort, used wherever the planner needs an ordering.

Merge sort is stable (equal keys keep their input order) and always runs in
O(n log n) time with O(n) extra space. The planner always passes keys that end
with the attraction id, so results are deterministic: same input, same order.
"""


def merge_sort(items, key=lambda x: x):
    """Return a new list with `items` sorted ascending by key(item)."""
    items = list(items)
    if len(items) <= 1:
        return items

    middle = len(items) // 2
    left = merge_sort(items[:middle], key)
    right = merge_sort(items[middle:], key)
    return _merge(left, right, key)


def _merge(left, right, key):
    """Merge two sorted lists into one sorted list in O(len(left) + len(right))."""
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        # "<=" keeps the sort stable: on a tie the left (earlier) item goes first.
        if key(left[i]) <= key(right[j]):
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


def rank_by_score(ids, scores):
    """Ids ordered by score (highest first), ties broken by smaller id."""
    return merge_sort(ids, key=lambda i: (-scores[i], i))
