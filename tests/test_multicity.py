"""Requirement 4: nearby-city trips (pairwise 100 km rule, intercity travel, missing connections)."""

from werkzeug.datastructures import MultiDict

from conftest import MONDAY, RATE, make_trip
from database.db import connect
from database import queries
from services.itinerary_generator import plan_trip
from services.multicity import centre_distance_km, group_problems, nearby_cities
from services.trip_request import parse_trip

TESTVILLE_ONLY = ("fort", "museum", "temple", "garden", "island", "aarti", "palace", "chaat-street")


def city_rows(tiny_db):
    conn = connect(tiny_db)
    try:
        return {r["slug"]: dict(r) for r in queries.list_cities(conn)}
    finally:
        conn.close()


def test_distances_and_nearby_list(tiny_db):
    rows = city_rows(tiny_db)
    assert 39 < centre_distance_km(rows["testville"], rows["riverton"]) < 41
    assert 105 < centre_distance_km(rows["riverton"], rows["westford"]) < 115
    near = [(c["slug"], round(km)) for c, km in nearby_cities(rows["testville"], rows.values())]
    assert [s for s, _ in near] == ["riverton", "westford"]          # nearest first; farville is too far


def test_rule_is_pairwise_not_just_from_the_base(tiny_db):
    rows = city_rows(tiny_db)
    assert group_problems([rows["testville"], rows["riverton"]]) == []
    assert group_problems([rows["testville"], rows["westford"]]) == []
    problems = group_problems([rows["testville"], rows["riverton"], rows["westford"]])
    assert len(problems) == 1 and "Riverton and Westford" in problems[0]
    assert group_problems([rows["testville"], rows["farville"]])


def test_trip_validation_refuses_an_ineligible_group(tiny_area, tiny_db):
    def load(slugs):
        return tiny_area(*slugs)
    categories = {"history"}
    ok, errors, _ = parse_trip(MultiDict({"city": "testville", "also": "riverton", "start": "hotel"}), load, categories)
    assert errors == {} and ok.extra_cities == ("riverton",)
    _, errors, _ = parse_trip(MultiDict({"city": "testville", "also": "riverton,westford"}), load, categories)
    assert "Riverton and Westford" in errors["also"]
    _, errors, _ = parse_trip(MultiDict({"city": "testville", "also": "farville"}), load, categories)
    assert "limit is 100 km" in errors["also"]
    _, errors, _ = parse_trip(MultiDict({"city": "testville", "also": "atlantis"}), load, categories)
    assert "Unknown city" in errors["also"]


def test_combined_pool_and_intercity_legs(tiny_area):
    area = tiny_area("testville", "riverton")
    assert {a.city_slug for a in area.attractions.values()} == {"testville", "riverton"}
    # With every Testville sight excluded, the day must be spent in Riverton.
    trip = make_trip(extra_cities=("riverton",), exclude=TESTVILLE_ONLY, days=1)
    plan = plan_trip(area, trip, RATE)
    assert plan.violations == []
    day = plan.days[0]
    assert day.visits and all(v.attraction.city_slug == "riverton" for v in day.visits)
    assert day.visits[0].leg.intercity and day.return_leg.intercity
    assert day.intercity_min == day.visits[0].leg.minutes + day.return_leg.minutes > 0
    assert day.local_travel_min == day.travel_min - day.intercity_min
    assert day.focus == "Riverton"
    assert plan.estimated_links == []                               # a real road link exists in the data


def test_missing_connection_uses_a_labelled_estimate_never_zero(tiny_area):
    area = tiny_area("testville", "westford")
    assert [(a, b) for a, b, _ in area.estimated_links] == [("testville", "westford")]
    hotel, temple = area.place("hotel").id, area.place("west-temple").id
    leg = area.leg(hotel, temple)
    assert leg.estimated and leg.intercity and leg.minutes > 60          # about 70 km: well over an hour
    trip = make_trip(extra_cities=("westford",), exclude=TESTVILLE_ONLY, day_end=21 * 60)
    plan = plan_trip(area, trip, RATE)
    assert plan.violations == []
    assert plan.estimated_links and any(v.leg.estimated for v in plan.visits)


def test_multi_city_trips_always_validate(tiny_area):
    area = tiny_area("testville", "riverton")
    for strategy in ("dp", "greedy", "max_visits"):
        for days in (1, 2, 3):
            trip = make_trip(extra_cities=("riverton",), strategy=strategy, days=days, day_end=20 * 60,
                             interests=("history", "markets"))
            plan = plan_trip(area, trip, RATE)
            assert plan.violations == [], (strategy, days, plan.violations)
            planned = {v.attraction.id for v in plan.visits}
            explained = {s.attraction.id for s in plan.skipped}
            assert planned | explained == set(area.attractions)


def test_days_are_grouped_by_city(tiny_area):
    """Each day keeps the best of 'all cities together' and 'one city at a time', so a day never zig-zags
    between cities more than once (out and back)."""
    area = tiny_area("testville", "riverton")
    plan = plan_trip(area, make_trip(extra_cities=("riverton",), days=3, day_end=20 * 60), RATE)
    for day in plan.days:
        cities = [v.attraction.city_slug for v in day.visits]
        changes = sum(1 for a, b in zip(cities, cities[1:]) if a != b)
        assert changes <= 1


def test_real_agra_mathura_vrindavan(real_area):
    area = real_area("agra", "mathura", "vrindavan")
    assert area.estimated_links == []                               # OSRM intercity links exist for every pair
    from datetime import date
    trip = make_trip(city="agra", start="tajganj-start", extra_cities=("mathura", "vrindavan"), days=3,
                     start_date=date(2026, 11, 2), interests=("spirituality",))
    plan = plan_trip(area, trip, RATE)
    assert plan.violations == []
    assert "mathura" in {v.attraction.city_slug for v in plan.visits}
    # Vrindavan is ~100 planned minutes from the Agra base each way, so on a 09:00-19:00 day it loses to
    # closer places -- and the plan says so. With only Vrindavan left it is planned like any other city.
    others = tuple(a.slug for a in area.attractions.values() if a.city_slug != "vrindavan")
    only_vrindavan = plan_trip(area, trip.with_changes(exclude=others, days=1), RATE)
    assert only_vrindavan.violations == [] and only_vrindavan.stops > 0
    assert {v.attraction.city_slug for v in only_vrindavan.visits} == {"vrindavan"}
