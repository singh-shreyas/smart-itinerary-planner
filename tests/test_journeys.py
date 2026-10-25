"""Requirement 1 (trip dates, longer trips) and Requirement 3 (multi-city journeys with moving stays)."""

from datetime import date, timedelta

import pytest

from conftest import LUNCH
from services.itinerary_generator import plan_trip
from services.journey import journey_stops
from services.models import TripRequest
from services.trip_request import parse_trip

START = date(2026, 11, 2)


def trip(city, days, start, end="", also=(), mode="suggested", overnight="move", places=(), **kw):
    values = dict(city=city, extra_cities=tuple(sorted(also)), start_date=START, days=days, day_start=540, day_end=1140,
                  interests=(), pace="balanced", start=start, end=end, strategy="dp", mode=mode, overnight=overnight,
                  places=tuple(places), lunch=LUNCH)
    values.update(kw)
    return TripRequest(**values)


def cities_by_day(plan):
    return [d.end_place.city_slug for d in plan.days]


def assert_continuous(plan, first, last):
    """Day 1 starts at the starting stay, every day starts where the last night was spent, the trip ends at `last`."""
    assert plan.days[0].start_place.slug == first
    for before, after in zip(plan.days, plan.days[1:]):
        assert after.start_place.id == before.end_place.id
    assert plan.days[-1].end_place.slug == last


def never_returns(plan, allowed_return=None):
    """Once the journey leaves a city it does not come back (except to finish a round trip)."""
    seen, current = [], None
    for slug in cities_by_day(plan):
        if slug != current:
            if slug in seen and slug != allowed_return:
                return False
            seen.append(slug)
            current = slug
    return True


# ------------------------------------------------------------------------------------------- dates

@pytest.mark.parametrize("days", [1, 5, 7, 10, 14])
def test_trip_length_comes_from_the_dates(client, days):
    end = START + timedelta(days=days - 1)
    data = client.get(f"/api/itinerary?city=delhi&start_date={START}&end_date={end}").get_json()
    assert data["violations"] == []
    dates = [d["date"] for d in data["days"]]
    assert len(dates) == days and dates[0] == START.isoformat() and dates[-1] == end.isoformat()
    assert dates == sorted(dates) and len(set(dates)) == days                 # every day once, in order


def test_dates_are_validated(client):
    for query, message in [("start_date=2026-11-05&end_date=2026-11-04", "cannot be before"),
                           ("start_date=2026-11-01&end_date=2026-12-31", "up to 30 days"),
                           ("start_date=2026-11-01&end_date=soon", "end date as YYYY-MM-DD"),
                           ("start_date=nope&end_date=2026-11-02", "start date as YYYY-MM-DD")]:
        response = client.get(f"/api/itinerary?city=delhi&{query}")
        assert response.status_code == 400 and message in str(response.get_json()["errors"]), query


def test_a_single_day_and_an_old_days_link_still_work(client):
    one = client.get(f"/api/itinerary?city=agra&start_date={START}&end_date={START}").get_json()
    assert len(one["days"]) == 1
    old = client.get(f"/api/itinerary?city=agra&start_date={START}&days=3").get_json()
    assert len(old["days"]) == 3                                                # links from before end dates


def test_long_trips_work_in_every_mode(real_cities):
    delhi = real_cities["delhi"]
    places = tuple(sorted(a.slug for a in delhi.attractions.values() if a.timed and not a.is_food_or_shopping_only)[:12])
    for mode in ("evenly", "suggested", "optimized"):
        plan = plan_trip(delhi, trip("delhi", 14, "delhi-stay-central", mode=mode, places=places))
        assert plan.violations == [] and len(plan.days) == 14
        assert plan.stops == len(places)
        assert [d.date for d in plan.days] == [START + timedelta(days=i) for i in range(14)]
    even = plan_trip(delhi, trip("delhi", 14, "delhi-stay-central", mode="evenly", places=places))
    assert sum(1 for d in even.days if d.visits) == 12                           # 12 places, 14 days: one a day
    fast = plan_trip(delhi, trip("delhi", 14, "delhi-stay-central", mode="optimized", places=places))
    assert sum(1 for d in fast.days if d.visits) < 12


# ---------------------------------------------------------------------------------------- journeys

def test_one_way_rishikesh_to_haridwar(real_area):
    area = real_area("rishikesh", "haridwar")
    for mode in ("evenly", "suggested", "optimized"):
        plan = plan_trip(area, trip("rishikesh", 4, "rishikesh-stay-central", end="haridwar-stay-central",
                                    also=("haridwar",), mode=mode))
        assert plan.violations == [], (mode, plan.violations)
        assert_continuous(plan, "rishikesh-stay-central", "haridwar-stay-central")
        assert never_returns(plan)                                              # no Rishikesh -> Haridwar -> Rishikesh
        for d in plan.days:
            # A day in Haridwar only visits Haridwar; Rishikesh's places are done before the move.
            if d.start_place.city_slug == d.end_place.city_slug == "haridwar":
                assert all(v.attraction.city_slug == "haridwar" for v in d.visits)


def test_the_transfer_takes_real_time_in_that_day(real_area):
    area = real_area("rishikesh", "haridwar")
    plan = plan_trip(area, trip("rishikesh", 3, "rishikesh-stay-central", end="haridwar-stay-central",
                                also=("haridwar",), mode="optimized"))
    move = next(d for d in plan.days if d.moves)
    assert move.intercity_min > 0 and move.intercity_min <= move.travel_min
    road = area.plan[move.start_place.id][move.end_place.id]
    assert move.return_time - move.depart >= road                               # never "appears" in the next city


def test_round_trip_returns_only_at_the_end(real_area):
    area = real_area("rishikesh", "haridwar")
    plan = plan_trip(area, trip("rishikesh", 4, "rishikesh-stay-central", also=("haridwar",), mode="evenly"))
    assert plan.violations == []
    assert_continuous(plan, "rishikesh-stay-central", "rishikesh-stay-central")
    assert never_returns(plan, allowed_return="rishikesh")
    assert cities_by_day(plan)[-2] == "haridwar"


def test_three_city_one_way_journey(real_area):
    area = real_area("rishikesh", "haridwar", "mussoorie")
    stops = journey_stops(area, trip("rishikesh", 6, "rishikesh-stay-central", end="haridwar-stay-west",
                                     also=("haridwar", "mussoorie")))
    assert [s for s, _ in stops] == ["rishikesh", "mussoorie", "haridwar"]       # ends where you chose
    for mode in ("evenly", "suggested", "optimized"):
        plan = plan_trip(area, trip("rishikesh", 7, "rishikesh-stay-central", end="haridwar-stay-west",
                                    also=("haridwar", "mussoorie"), mode=mode))
        assert plan.violations == [], (mode, plan.violations)
        assert_continuous(plan, "rishikesh-stay-central", "haridwar-stay-west")
        assert never_returns(plan)
        assert len(plan.journey) == 3 and sum(1 for d in plan.days if d.moves) == 2


def test_different_start_and_end_areas_of_one_city(real_cities):
    delhi = real_cities["delhi"]
    plan = plan_trip(delhi, trip("delhi", 3, "delhi-stay-central", end="delhi-stay-south"))
    assert plan.violations == []
    assert_continuous(plan, "delhi-stay-central", "delhi-stay-south")
    assert sum(1 for d in plan.days if d.moves) == 1


def test_one_base_still_returns_home_every_night(real_area):
    area = real_area("rishikesh", "haridwar")
    plan = plan_trip(area, trip("rishikesh", 2, "rishikesh-stay-central", also=("haridwar",), overnight="base"))
    assert plan.violations == [] and not plan.journey
    assert all(d.start_place.slug == d.end_place.slug == "rishikesh-stay-central" for d in plan.days)


def test_opening_hours_hold_on_journeys(real_area):
    """The validator checks every visit against that weekday's hours; a 9-day journey must pass."""
    area = real_area("agra", "mathura", "vrindavan")
    plan = plan_trip(area, trip("agra", 9, "agra-stay-central", end="vrindavan-stay-central",
                                also=("mathura", "vrindavan"), mode="suggested"))
    assert plan.violations == [] and len(plan.days) == 9
    assert_continuous(plan, "agra-stay-central", "vrindavan-stay-central")
    assert never_returns(plan)


def test_too_short_for_the_moves_is_explained(client):
    response = client.get(f"/api/itinerary?city=rishikesh&also=haridwar,mussoorie&start_date={START}&end_date={START}"
                          "&overnight=move&end=haridwar-stay-central")
    assert response.status_code == 400 and "needs at least" in response.get_json()["errors"]["end"]
    # A link that does not ask for moving stays falls back to one base with day trips.
    ok = client.get(f"/api/itinerary?city=rishikesh&also=haridwar&start_date={START}&end_date={START}")
    assert ok.status_code == 200 and ok.get_json()["overnight"] == "base"


def test_end_stay_must_belong_to_the_trip(client, real_db):
    def load(slugs):
        from routes.helpers import city_data
        return city_data(slugs[0], slugs[1:])
    with client.application.test_request_context():
        _, errors, _ = parse_trip({"city": "rishikesh", "also": "haridwar", "start_date": "2026-11-02",
                                   "end_date": "2026-11-05", "end": "agra-stay-central"}, load, set())
    assert "end" in errors


def test_api_reports_each_night(client):
    data = client.get(f"/api/itinerary?city=rishikesh&also=haridwar&start_date={START}&end_date={START + timedelta(days=2)}"
                      "&end=haridwar-stay-central").get_json()
    assert data["overnight"] == "move" and data["end"] == "haridwar-stay-central"
    assert data["days"][-1]["night_at"] == "haridwar-stay-central"
    assert [d["starts_at"] for d in data["days"][1:]] == [d["night_at"] for d in data["days"][:-1]]
