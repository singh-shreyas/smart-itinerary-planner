"""Requirement 9: travel durations are planned and shown in 10-minute steps (rounded UP); clock times are not."""

import math

import pytest

from conftest import make_trip
from services.itinerary_generator import plan_trip
from services.timeutil import fmt_duration, fmt_hhmm, fmt_travel, round_up_travel


@pytest.mark.parametrize("raw, planned", [(0, 0), (1, 10), (9, 10), (10, 10), (11, 20), (14, 20), (20, 20),
                                          (59, 60), (61, 70), (130, 130), (math.inf, math.inf)])
def test_round_up_rule(raw, planned):
    assert round_up_travel(raw) == planned


@pytest.mark.parametrize("minutes, text", [(20, "20 min"), (70, "1 hr 10 min"), (120, "2 hr"), (0, "0 min")])
def test_duration_format(minutes, text):
    assert fmt_duration(minutes) == text


def test_travel_format_handles_zero_and_missing():
    assert fmt_travel(0) == "no travel"
    assert fmt_travel(math.inf) == "no route"
    assert fmt_travel(30) == "30 min"
    assert "sec" not in fmt_travel(10)


def test_planning_table_is_the_raw_table_rounded_up(tiny_city):
    for u, row in tiny_city.dist.items():
        for v, raw in row.items():
            planned = tiny_city.plan[u][v]
            assert planned == round_up_travel(raw)
            if raw != math.inf:
                assert planned % 10 == 0 and raw <= planned < raw + 10


def test_every_leg_is_a_multiple_of_ten_and_the_timeline_adds_up(tiny_city):
    plan = plan_trip(tiny_city, make_trip(days=2, day_end=20 * 60))
    assert plan.violations == []
    for day in plan.days:
        for leg in day.legs:
            assert leg.minutes % 10 == 0 and leg.minutes >= leg.raw_minutes
            assert leg.arrive == leg.depart + leg.minutes
        for visit in day.visits:
            assert visit.arrive == visit.leg.depart + visit.leg.minutes      # displayed times agree with the legs


def test_clock_times_are_not_rounded(tiny_city):
    """Only travel durations are rounded: a 09:05 start stays 09:05 and visits keep their own lengths."""
    plan = plan_trip(tiny_city, make_trip(day_start=9 * 60 + 5, exclude=("museum",)))
    day = plan.days[0]
    assert fmt_hhmm(day.depart) == "09:05"
    assert all(v.end - v.start == v.attraction.visit_min for v in day.visits)
