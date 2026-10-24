"""Shared test fixtures.

Two databases are built once per test session in a temporary folder:
  tiny_db -- the hand-made fixture city in tests/fixtures/tiny_city (answers checkable on paper)
  real_db -- the real data in data/ (the 50 destinations)
The real instance/itinerary.db is never touched by the tests.
"""

import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import create_app                                  # noqa: E402
from database.db import connect                             # noqa: E402
from database.seed_data import seed_database                # noqa: E402
from services.city_data import clear_cache, load_area, load_city  # noqa: E402
from services.models import MealSetting, TripRequest        # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "tiny_city")
DATA_DIR = os.path.join(ROOT, "data")
MONDAY = date(2026, 11, 2)            # a known Monday, so weekday rules are testable
RATE = 12                             # rupees per km for the transport estimate


@pytest.fixture(scope="session")
def tiny_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("db") / "tiny.db")
    seed_database(path, FIXTURE_DIR)
    return path


@pytest.fixture(scope="session")
def real_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("db") / "real.db")
    seed_database(path, DATA_DIR)
    return path


@pytest.fixture(scope="session")
def tiny_city(tiny_db):
    conn = connect(tiny_db)
    try:
        return load_city(conn, "testville", traffic_factor=1.0)
    finally:
        conn.close()


@pytest.fixture(scope="session")
def real_cities(real_db):
    conn = connect(real_db)
    try:
        return {slug: load_city(conn, slug, traffic_factor=1.5) for slug in ("delhi", "agra", "jaipur", "varanasi")}
    finally:
        conn.close()


@pytest.fixture(scope="session")
def tiny_area(tiny_db):
    """Loader for a group of fixture cities: tiny_area("testville", "riverton")."""
    cache = {}

    def load(*slugs):
        if slugs not in cache:
            conn = connect(tiny_db)
            try:
                cache[slugs] = load_area(conn, list(slugs), traffic_factor=1.0)
            finally:
                conn.close()
        return cache[slugs]
    return load


@pytest.fixture(scope="session")
def real_area(real_db):
    """Loader for a group of real cities: real_area("agra", "mathura")."""
    cache = {}

    def load(*slugs):
        if slugs not in cache:
            conn = connect(real_db)
            try:
                cache[slugs] = load_area(conn, list(slugs), traffic_factor=1.5)
            finally:
                conn.close()
        return cache[slugs]
    return load


@pytest.fixture(scope="session")
def app(real_db):
    clear_cache()
    return create_app({"TESTING": True, "DATABASE": real_db, "AUTO_SEED": False})


@pytest.fixture
def client(app):
    return app.test_client()


def make_trip(**overrides):
    """A valid TripRequest for the fixture city; override any field."""
    values = dict(city="testville", start_date=MONDAY, days=1, day_start=9 * 60, day_end=19 * 60,
                  budget=None, include_transport=False, interests=(), pace="balanced", start="hotel",
                  strategy="dp", exclude=())
    values.update(overrides)
    return TripRequest(**values)


LUNCH = MealSetting("lunch", 12 * 60, 14 * 60 + 30, 45)
DINNER = MealSetting("dinner", 19 * 60, 21 * 60 + 30, 60)
