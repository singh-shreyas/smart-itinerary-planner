"""Activity selection and the time-window scheduler (opening hours, last entry, day end)."""

import math
from datetime import timedelta

from algorithms.activity_selection import earliest_deadline_order, select_activities
from conftest import MONDAY, make_trip
from services.itinerary_generator import day_context
from services.scheduler import earliest_start, simulate

TUESDAY = MONDAY + timedelta(days=1)


def test_textbook_activity_selection():
    # CLRS example: 11 activities (id, start, finish); the greedy rule picks a1, a4, a8, a11.
    start = [1, 3, 0, 5, 3, 5, 6, 8, 8, 2, 12]
    finish = [4, 5, 6, 7, 9, 9, 10, 11, 12, 14, 16]
    activities = [(i + 1, s, f) for i, (s, f) in enumerate(zip(start, finish))]
    assert select_activities(activities) == [1, 4, 8, 11]
    assert select_activities([]) == []


def test_chosen_activities_never_overlap():
    chosen = select_activities([(1, 0, 10), (2, 5, 7), (3, 7, 9), (4, 9, 12)])
    assert chosen == [2, 3, 4]


def test_earliest_deadline_order_breaks_ties_by_id():
    closing = {10: 900, 11: 600, 12: 600, 13: 1200}
    assert earliest_deadline_order([13, 12, 10, 11], closing) == [11, 12, 10, 13]


def ctx_for(city, trip, day):
    return day_context(city, trip, day)


def test_closed_weekday_is_a_violation(tiny_city):
    museum = tiny_city.place("museum").id
    monday = simulate([museum], ctx_for(tiny_city, make_trip(), MONDAY))
    assert not monday.feasible and "closed on Monday" in monday.violations[0]
    assert simulate([museum], ctx_for(tiny_city, make_trip(), TUESDAY)).feasible


def test_split_hours_are_never_spanned(tiny_city):
    temple = tiny_city.attractions[tiny_city.place("temple").id]
    assert earliest_start(temple, 0, 11 * 60) == 11 * 60          # fits before the 12:00 break
    assert earliest_start(temple, 0, 11 * 60 + 30) == 16 * 60     # 45 min would span the break: wait for 16:00
    assert earliest_start(temple, 0, 19 * 60 + 30) is None        # too late for the evening window


def test_last_entry_is_respected(tiny_city):
    aarti = tiny_city.attractions[tiny_city.place("aarti").id]
    assert earliest_start(aarti, 0, 17 * 60) == 18 * 60           # waits for opening
    assert earliest_start(aarti, 0, 18 * 60 + 30) == 18 * 60 + 30  # exactly the last entry
    assert earliest_start(aarti, 0, 18 * 60 + 31) is None


def test_waiting_for_the_first_stop_means_leaving_later(tiny_city):
    trip = make_trip(day_start=6 * 60)
    fort = tiny_city.place("fort").id
    schedule = simulate([fort], ctx_for(tiny_city, trip, MONDAY), detailed=True)
    visit = schedule.visits[0]
    assert visit.start == 9 * 60 and visit.wait == 0
    assert schedule.depart == 9 * 60 - 10                          # 10-minute ride, leave at 08:50


def test_day_end_includes_the_ride_back(tiny_city):
    fort = tiny_city.place("fort").id
    # 09:00 + 10 travel + 60 visit + 15 buffer + 10 back = 10:35
    assert simulate([fort], ctx_for(tiny_city, make_trip(day_end=10 * 60 + 35), MONDAY)).feasible
    late = simulate([fort], ctx_for(tiny_city, make_trip(day_end=10 * 60 + 34), MONDAY))
    assert not late.feasible and "after your day ends" in late.violations[0]


def test_unreachable_stop_is_never_feasible(tiny_city):
    island = tiny_city.place("island").id
    schedule = simulate([island], ctx_for(tiny_city, make_trip(), MONDAY))
    assert not schedule.feasible and schedule.travel_min == math.inf


def test_timeline_is_sequential_without_overlaps(tiny_city):
    ids = [tiny_city.place(s).id for s in ("fort", "museum", "garden", "aarti")]
    # The aarti ends at 19:00 and the ride back takes 30 minutes, so the day must run to 20:00.
    schedule = simulate(ids, ctx_for(tiny_city, make_trip(day_end=20 * 60), TUESDAY), detailed=True)
    assert schedule.feasible and schedule.end_time == 19 * 60 + 15 + 30
    for previous, current in zip(schedule.visits, schedule.visits[1:]):
        assert current.arrive == previous.leave + current.leg.minutes
        assert current.start >= current.arrive >= previous.end
