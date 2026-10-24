"""SQLite connection handling.

One connection per request, stored on flask.g and closed when the request
ends. Foreign keys are OFF by default in SQLite, so every new connection turns
them on.
"""

import os
import sqlite3

import click
from flask import current_app, g


def connect(path):
    """Open a connection with rows accessible by column name and FKs enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """The current request's connection (opened on first use)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def database_ready(path):
    """True if the file exists and contains at least one city."""
    if not os.path.exists(path):
        return False
    try:
        conn = connect(path)
        try:
            return conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0] > 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False


@click.command("init-db")
@click.option("--strict", is_flag=True, help="Also refuse rows marked illustrative.")
def init_db_command(strict):
    """Rebuild the database from the CSV files in data/."""
    from database.seed_data import seed_database
    summary = seed_database(current_app.config["DATABASE"], current_app.config["DATA_DIR"], strict=strict)
    for warning in summary["warnings"]:
        click.echo(f"warning: {warning}")
    click.echo(f"Database built: {summary['cities']} cities, {summary['attractions']} attractions, "
               f"{summary['edges']} travel edges -> {current_app.config['DATABASE']}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
