"""Requirement 1: identical inputs + identical data + identical settings => identical itinerary."""

import json
import os
import subprocess
import sys
from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from algorithms.dynamic_programming import dp_select
from algorithms.greedy import greedy_select
from algorithms.knapsack_types import Item
from conftest import DINNER, LUNCH, ROOT, make_trip
from database import migrations
from routes.helpers import itinerary_to_dict
from services import versioning
from services.itinerary_generator import plan_trip
from services.trip_request import parse_trip


def plan_dict(city, trip):
    data = itinerary_to_dict(plan_trip(city, trip))
    data.pop("runtime_ms")
    return data


@pytest.mark.parametrize("strategy", ["dp", "greedy"])
def test_same_trip_twice_gives_the_same_plan(tiny_area, strategy):
    area = tiny_area("testville", "riverton")
    trip = make_trip(extra_cities=("riverton",), strategy=strategy, days=3, day_end=21 * 60, lunch=LUNCH,
                     dinner=DINNER, interests=("history", "food"))
    first, second = plan_dict(area, trip), plan_dict(area, trip)
    assert first == second
    assert first["versions"]["plan"] == second["versions"]["plan"]


def test_real_data_plan_is_reproducible(real_cities):
    trip = make_trip(city="delhi", start="delhi-stay-central", start_date=date(2026, 11, 2), days=3, day_end=21 * 60,
                     lunch=LUNCH, dinner=DINNER, interests=("history",))
    assert plan_dict(real_cities["delhi"], trip) == plan_dict(real_cities["delhi"], trip)


SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from database.db import connect
from services.city_data import load_area
from services.itinerary_generator import plan_trip
from services.models import MealSetting, TripRequest
from datetime import date
conn = connect(sys.argv[2])
area = load_area(conn, ["testville", "riverton"], 1.0)
trip = TripRequest(city="testville", start_date=date(2026, 11, 2), days=3, day_start=540, day_end=1260,
                   interests=("history", "food"), pace="balanced", start="hotel",
                   strategy=sys.argv[3], extra_cities=("riverton",), lunch=MealSetting("lunch", 720, 870, 45))
print(plan_trip(area, trip).versions["plan"])
"""


@pytest.mark.parametrize("strategy", ["dp", "greedy"])
def test_plan_does_not_depend_on_python_hash_randomisation(tiny_db, strategy):
    """Set iteration order changes with PYTHONHASHSEED; the plan must not."""
    outputs = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run([sys.executable, "-c", SCRIPT, ROOT, tiny_db, strategy], env=env,
                                capture_output=True, text=True, check=True)
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, outputs


@pytest.mark.parametrize("select", [dp_select, greedy_select])
def test_ties_are_broken_by_the_smaller_id(select):
    """Two identical places, room for one: the earlier row in the dataset (smaller id) wins, every time."""
    items = [Item(7, 50, 5), Item(9, 50, 5)]
    assert select(items, 5).chosen == [7]


def test_input_order_does_not_matter(tiny_area):
    def load(slugs):
        return tiny_area(*slugs)
    a, _, _ = parse_trip(MultiDict([("city", "testville"), ("interests", "nature"), ("interests", "history"),
                                    ("exclude", "palace,fort")]), load, {"history", "nature"})
    b, _, _ = parse_trip(MultiDict([("city", "testville"), ("interests", "history,nature"),
                                    ("exclude", "fort"), ("exclude", "palace")]), load, {"history", "nature"})
    assert a == b and a.interests == ("history", "nature")


def test_fingerprints_separate_data_and_setting_changes(tmp_path):
    import shutil
    from conftest import FIXTURE_DIR
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    before = migrations.dataset_fingerprint(str(data))
    assert before == migrations.dataset_fingerprint(str(data))       # stable
    with open(data / "attractions.csv", "a", encoding="utf-8") as f:
        f.write("\n")
    assert migrations.dataset_fingerprint(str(data)) != before        # a data change is a new data version
    assert versioning.settings_version() == versioning.settings_version()
    assert len(versioning.settings_version()) == 10
