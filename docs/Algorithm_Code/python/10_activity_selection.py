# Activity selection, and earliest-deadline ordering (as in algorithms/activity_selection.py)

def select_activities(intervals):
    """intervals: (id, start, finish). Returns a maximum set of non-overlapping ids."""
    by_finish = sorted(intervals, key=lambda x: (x[2], x[1], x[0]))   # project: merge_sort
    chosen, last_finish = [], float("-inf")
    for activity_id, start, finish in by_finish:
        if start >= last_finish:
            chosen.append(activity_id)
            last_finish = finish
    return chosen


def earliest_deadline_order(stops, closing_time):
    """Stops by closing time, earliest first; ties by id."""
    return sorted(stops, key=lambda s: (closing_time[s], s))


if __name__ == "__main__":
    talks = [("a", 9, 11), ("b", 10, 12), ("c", 11, 13), ("d", 12, 14), ("e", 13, 15)]
    print(select_activities(talks))
    print(earliest_deadline_order([1, 2, 3, 4], {1: 18 * 60, 2: 17 * 60, 3: 21 * 60, 4: 17 * 60}))
