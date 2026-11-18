# Merge sort, stable (as in algorithms/sorting.py)

def merge_sort(items, key=lambda x: x):
    items = list(items)
    if len(items) <= 1:
        return items
    middle = len(items) // 2
    left = merge_sort(items[:middle], key)
    right = merge_sort(items[middle:], key)
    return merge(left, right, key)


def merge(left, right, key):
    merged, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        if key(left[i]) <= key(right[j]):      # "<=" keeps equal keys in input order (stable)
            merged.append(left[i]); i += 1
        else:
            merged.append(right[j]); j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


def rank_by_score(ids, scores):
    """Highest score first; ties go to the smaller id."""
    return merge_sort(ids, key=lambda i: (-scores[i], i))


if __name__ == "__main__":
    scores = {101: 72, 102: 90, 103: 72, 104: 55, 105: 90}
    print(rank_by_score(list(scores), scores))
