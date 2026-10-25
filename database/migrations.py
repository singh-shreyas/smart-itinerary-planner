"""Safe database updates: versions, fingerprints, backups.

The database holds two kinds of tables:

  * reference tables (cities, places, attractions, ...) -- generated from the
    CSV files in data/ and safe to rebuild at any time;
  * anything else (for example a table of saved trips or settings added in a
    later version) -- treated as USER data and never dropped.

A rebuild therefore works like this (database/seed_data.py does the writing):

    1. validate every CSV and build a complete new database in a temporary file
    2. copy every non-reference table, with its rows, from the old database
    3. copy the old database file to instance/backups/ (newest few kept)
    4. atomically swap the new file into place

If any step fails, the old database is left exactly as it was.

The `meta` table records the schema version and a fingerprint (SHA-256) of the
CSV files the database was built from. On start-up the app compares them with
the current code and data and rebuilds only when something actually changed,
so a dataset update is always visible as a new "data version".
"""

import glob
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime

SCHEMA_VERSION = 3

REFERENCE_TABLES = {"meta", "cities", "places", "stay_areas", "categories", "attractions", "attraction_categories",
                    "opening_hours", "travel_edges", "access_segments", "access_alternatives"}


def dataset_fingerprint(data_dir):
    """SHA-256 over every planning CSV in data_dir (file names and contents).

    Line endings are normalised so a checkout on Windows gives the same value.
    The catalog/ and curation/ subfolders are not read by the planner, so they
    are not part of the fingerprint.
    """
    digest = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        digest.update(os.path.basename(path).encode())
        with open(path, "rb") as f:
            digest.update(f.read().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def read_meta(db_path):
    """The meta table as a dict; {} for a missing file or a database built before meta existed."""
    if not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            return {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
        finally:
            conn.close()
    except sqlite3.Error:
        return {}


def rebuild_reason(db_path, data_dir):
    """Why the database must be rebuilt, or None if it is up to date."""
    if not os.path.exists(db_path):
        return "no database yet"
    meta = read_meta(db_path)
    if not meta:
        return "database predates versioning (schema 1)"
    if int(meta.get("schema_version", 0)) != SCHEMA_VERSION:
        return f"schema version {meta.get('schema_version')} -> {SCHEMA_VERSION}"
    if meta.get("dataset_fingerprint") != dataset_fingerprint(data_dir):
        return "data/*.csv changed"
    return None


def user_tables(conn):
    """Tables that are not rebuilt from CSV (user data). Never dropped."""
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    return [(name, sql) for name, sql in rows if name not in REFERENCE_TABLES]


def copy_user_tables(old_path, new_conn):
    """Copy every user table (schema + rows) from the old database into new_conn. Returns the names."""
    if not os.path.exists(old_path):
        return []
    try:
        old = sqlite3.connect(old_path)
    except sqlite3.Error:
        return []
    copied = []
    try:
        for name, sql in user_tables(old):
            new_conn.execute(sql)
            columns = [row[1] for row in old.execute(f'PRAGMA table_info("{name}")')]
            placeholders = ", ".join("?" for _ in columns)
            quoted = ", ".join(f'"{c}"' for c in columns)
            rows = old.execute(f'SELECT {quoted} FROM "{name}"').fetchall()
            new_conn.executemany(f'INSERT INTO "{name}" ({quoted}) VALUES ({placeholders})', rows)
            copied.append(name)
    finally:
        old.close()
    return copied


def backup(db_path, keep=5):
    """Copy db_path into backups/ next to it; keep only the newest `keep` copies. Returns the copy's path."""
    if not os.path.exists(db_path):
        return None
    folder = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(db_path))[0]
    target = os.path.join(folder, f"{stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.db")
    shutil.copy2(db_path, target)
    old_copies = sorted(glob.glob(os.path.join(folder, f"{stem}-*.db")))
    for path in old_copies[:-keep] if keep > 0 else old_copies:
        os.remove(path)
    return target
