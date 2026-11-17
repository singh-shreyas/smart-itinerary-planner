# Repair with a min-heap: drop the weakest stop when a day cannot be routed
# (as in services/itinerary_generator.py, solve_pool and weakest_key)
import heapq


def repair(candidates, select, route_ok, scores, minutes):
    """select(cands) -> chosen ids; route_ok(chosen) -> bool. Returns (chosen, dropped)."""
    candidates, dropped = list(candidates), []
    while candidates:
        chosen = select(candidates)
        if not chosen or route_ok(chosen):
            return chosen, dropped
        heap = [(scores[a] / minutes[a], scores[a], a) for a in chosen]   # value per minute
        heapq.heapify(heap)                    # weakest stop on top, O(k)
        victim = heapq.heappop(heap)[-1]       # O(log k)
        candidates.remove(victim)
        dropped.append(victim)
    return [], dropped


if __name__ == "__main__":
    scores = {1: 80, 2: 45, 3: 70, 4: 60}
    minutes = {1: 90, 2: 120, 3: 60, 4: 60}
    select_all = lambda cands: list(cands)                 # stand-in selector
    fits = lambda chosen: sum(minutes[a] for a in chosen) <= 240   # stand-in route check
    print(repair([1, 2, 3, 4], select_all, fits, scores, minutes))
