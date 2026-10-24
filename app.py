"""Smart Itinerary Planner and Travel Optimization System -- Flask application.

Run it (from the project folder, with the virtual environment active):

    python app.py                              # http://127.0.0.1:5001
    flask --app app run --debug --port 5001    # same, using the Flask CLI

Port 5001 is used because macOS AirPlay Receiver often occupies port 5000.
On first start the SQLite database is built automatically from data/*.csv.
"""

import logging
import os
from datetime import date

from flask import Flask, jsonify, render_template, request

import config
from config import Config
from database import db
from database.seed_data import SeedError, seed_database
from services.timeutil import WEEKDAY_LONG, WEEKDAY_SHORT, fmt_duration, fmt_hhmm


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    app.logger.setLevel(logging.INFO)

    db.init_app(app)
    if app.config["AUTO_SEED"] and not db.database_ready(app.config["DATABASE"]):
        try:
            summary = seed_database(app.config["DATABASE"], app.config["DATA_DIR"])
            app.logger.info("Built database: %s cities, %s attractions", summary["cities"], summary["attractions"])
        except SeedError as exc:
            app.logger.error("Could not build the database:\n%s", exc)

    _register_template_helpers(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    return app


def _register_template_helpers(app):
    app.add_template_filter(fmt_hhmm, "hhmm")
    app.add_template_filter(fmt_duration, "duration")
    app.add_template_filter(lambda n: f"₹{int(round(n)):,}", "inr")
    app.add_template_filter(lambda d: WEEKDAY_SHORT[d], "weekday_short")
    app.add_template_filter(lambda d: WEEKDAY_LONG[d], "weekday_long")
    app.add_template_filter(lambda d: d.strftime("%a %-d %b"), "short_date")
    app.add_template_filter(lambda d: d.strftime("%A, %-d %B %Y"), "long_date")

    @app.context_processor
    def inject_globals():
        return {
            "today": date.today(),
            "PACES": config.PACES,
            "STRATEGIES": config.STRATEGIES,
            "MAX_DAYS": config.MAX_DAYS,
            "TRAFFIC_FACTOR": app.config["TRAFFIC_FACTOR"],
            "TRANSPORT_RATE": app.config["TRANSPORT_COST_PER_KM"],
            "active_endpoint": request.endpoint or "",
        }


def _register_blueprints(app):
    from routes.api_routes import api
    from routes.itinerary_routes import planner
    from routes.main_routes import main

    app.register_blueprint(main)
    app.register_blueprint(planner)
    app.register_blueprint(api)


def _wants_json():
    return request.path.startswith("/api/")


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(_error):
        if _wants_json():
            return jsonify(error="not found"), 404
        return render_template("error.html", code=404, title="Page not found",
                               message="We couldn't find that page or destination."), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Unhandled error: %s", error)
        if _wants_json():
            return jsonify(error="internal server error"), 500
        return render_template("error.html", code=500, title="Something went wrong",
                               message="An unexpected error occurred. If the database is missing, run "
                                       "python -m database.seed_data and reload."), 500


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
