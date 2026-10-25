"""Safe database updates: versioning, backups, user data kept, nothing half-built."""

import os
import shutil
import sqlite3

import pytest

from conftest import FIXTURE_DIR
from database import migrations
from database.seed_data import SeedError, ensure_database, seed_database


def test_fresh_build_records_schema_and_data_version(tmp_path):
    path = str(tmp_path / "a.db")
    seed_database(path, FIXTURE_DIR)
    meta = migrations.read_meta(path)
    assert int(meta["schema_version"]) == migrations.SCHEMA_VERSION
    assert meta["dataset_fingerprint"] == migrations.dataset_fingerprint(FIXTURE_DIR)
    assert migrations.rebuild_reason(path, FIXTURE_DIR) is None


def test_up_to_date_database_is_left_alone(tmp_path):
    path = str(tmp_path / "a.db")
    seed_database(path, FIXTURE_DIR)
    before = os.path.getmtime(path)
    assert ensure_database(path, FIXTURE_DIR) is None
    assert os.path.getmtime(path) == before
    assert not os.path.exists(tmp_path / "backups")


def test_old_database_is_upgraded_with_backup_and_user_data_kept(tmp_path):
    """A schema-1 database (no meta table) with a user table is rebuilt: the user rows survive."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE cities (id INTEGER PRIMARY KEY, slug TEXT);
        INSERT INTO cities (slug) VALUES ('delhi');
        CREATE TABLE saved_trips (id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT);
        INSERT INTO saved_trips (name, url) VALUES ('Weekend', '/itinerary?city=delhi&days=2');
    """)
    conn.commit()
    conn.close()
    assert "predates versioning" in migrations.rebuild_reason(path, FIXTURE_DIR)

    reason = ensure_database(path, FIXTURE_DIR)
    assert reason is not None
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT name, url FROM saved_trips").fetchall() == [("Weekend", "/itinerary?city=delhi&days=2")]
    assert conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0] == 6
    conn.close()
    backups = os.listdir(tmp_path / "backups")
    assert len(backups) == 1
    old = sqlite3.connect(str(tmp_path / "backups" / backups[0]))
    assert old.execute("SELECT slug FROM cities").fetchall() == [("delhi",)]    # the backup is the old file
    old.close()


def test_changed_csv_triggers_a_rebuild(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    path = str(tmp_path / "a.db")
    seed_database(path, str(data))
    with open(data / "attractions.csv", "a", encoding="utf-8") as f:
        f.write("\n")                                        # any byte change is a new dataset version
    assert migrations.rebuild_reason(path, str(data)) == "data/*.csv changed"


def test_failed_rebuild_leaves_the_old_database_untouched(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    path = str(tmp_path / "a.db")
    seed_database(path, str(data))
    with open(path, "rb") as f:
        original = f.read()
    with open(data / "opening_hours.csv", "a", encoding="utf-8") as f:
        f.write("testville,fort,Daily,17:00,09:00,\n")
    with pytest.raises(SeedError):
        ensure_database(path, str(data))
    with open(path, "rb") as f:
        assert f.read() == original
    assert not os.path.exists(path + ".building")


def test_only_the_newest_backups_are_kept(tmp_path):
    path = str(tmp_path / "a.db")
    seed_database(path, FIXTURE_DIR)
    for _ in range(4):
        seed_database(path, FIXTURE_DIR, keep_backups=2)
    assert len(os.listdir(tmp_path / "backups")) == 2
