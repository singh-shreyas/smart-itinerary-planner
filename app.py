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

from flask import Flask, jsonify, redirect, render_template, request, url_for

import config
from config import Config
from database import db
from database.seed_data import SeedError, ensure_database
from services import i18n
from services.timeutil import WEEKDAY_LONG, WEEKDAY_SHORT, fmt_duration, fmt_hhmm, fmt_long_date, fmt_short_date, fmt_travel


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    app.logger.setLevel(logging.INFO)

    db.init_app(app)
    if app.config["AUTO_SEED"]:
        # Rebuild only if the database is missing, has an older schema, or was built
        # from different CSV files. The old file is backed up and user tables kept.
        try:
            ensure_database(app.config["DATABASE"], app.config["DATA_DIR"], app.logger)
        except SeedError as exc:
            app.logger.error("Could not build the database (the previous one, if any, is untouched):\n%s", exc)

    _register_template_helpers(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    return app


def _register_template_helpers(app):
    app.add_template_filter(fmt_hhmm, "hhmm")
    app.add_template_filter(fmt_duration, "duration")
    app.add_template_filter(fmt_travel, "travel")
    app.add_template_filter(lambda n: f"₹{int(round(n)):,}", "inr")
    app.add_template_filter(lambda d: i18n.gettext(WEEKDAY_SHORT[d]), "weekday_short")
    app.add_template_filter(lambda d: i18n.gettext(WEEKDAY_LONG[d]), "weekday_long")
    app.add_template_filter(fmt_short_date, "short_date")
    app.add_template_filter(fmt_long_date, "long_date")
    app.add_template_filter(lambda n: f"{n:,}" if isinstance(n, int) else n, "num")

    # Interface language: from the "lang" cookie, for templates, Python messages and scripts alike.
    app.jinja_env.globals["_"] = i18n.gettext
    app.jinja_env.globals["LANGUAGES"] = i18n.LANGUAGES

    @app.before_request
    def pick_language():
        i18n.set_language(request.cookies.get(i18n.COOKIE, i18n.DEFAULT))

    @app.route("/lang/<code>")
    def set_language(code):
        """Switch language and go back to the same page (same query string, so no trip input is lost)."""
        target = request.args.get("next") or url_for("main.index")
        if not target.startswith("/") or target.startswith("//"):
            target = url_for("main.index")                      # only ever redirect within this site
        response = redirect(target)
        response.set_cookie(i18n.COOKIE, i18n.clean(code), max_age=365 * 24 * 3600, samesite="Lax")
        return response

    def footer_data():
        """Top destinations and dataset totals for the footer. Never breaks a page (e.g. an error page)."""
        try:
            from database import queries
            conn = db.get_db()
            counts = queries.summary_counts(conn)
            return {"cities": queries.list_cities(conn)[:7], "city_count": counts["cities"],
                    "attraction_count": counts["attractions"], "edge_count": counts["edges"],
                    "data_version": queries.get_meta(conn).get("dataset_fingerprint", "")[:10]}
        except Exception:                       # database missing or broken: plain footer
            return {"cities": [], "city_count": 0}

    app.jinja_env.globals["MAX_DAYS"] = config.MAX_DAYS        # also visible inside imported macros

    @app.context_processor
    def inject_globals():
        return {
            "footer": footer_data(),
            "today": date.today(),
            "PACES": config.PACES,
            "STRATEGIES": config.STRATEGIES,
            "STRATEGY_SHORT": config.STRATEGY_SHORT,
            "MODES": config.MODES,
            "ROUNDING": config.TRAVEL_ROUNDING_MIN,
            "MAX_DAYS": config.MAX_DAYS,
            "TRAFFIC_FACTOR": app.config["TRAFFIC_FACTOR"],
            "active_endpoint": request.endpoint or "",
            "current_lang": i18n.current(),
            "js_i18n": i18n.js_catalog(JS_TEXTS),
        }


# Texts the page scripts show (site.js, planner.js, attractions.js, itinerary.js, compare.js). Each page gets
# their translations as a small JSON object, so client-side text follows the chosen language too.
JS_TEXTS = [
    "Load more", "Showing {shown} of {total}", "Select all ({n})", "Deselect all", "place selected", "places selected",
    "1 day (start and end dates included)", "{n} days (start and end dates included)",
    "Trips can be up to {max} days long; this one is {n} days.", "Recommended visit", "Entry (Indian adult)",
    "estimate", "estimate, please confirm", "from", "about {n} min", "Photo",
    "How long this takes is not known, so the planner does not schedule it; check locally.",
    "Switch to dark mode", "Switch to light mode", "Start of the day", "Start and end of the day", "Tonight's stay",
    "Day {n}", "Same as the starting stay", "Planning your trip…", "Closed", "planner chooses places",
    "{n} place picked", "{n} places picked", "{n} day", "{n} days", "No meal breaks", "Lunch break", "Dinner break",
    "Lunch and dinner breaks", "vegetarian places", "pace", "only", "from", "to",
    "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
    "Oct", "Nov", "Dec", "Photo not available", "Opening hours", "minutes", "Value", "Coverage", "Travel efficiency",
    "Time utilisation", "Overall", "Sightseeing", "Travel", "Meals", "Waiting", "Unused", "Day", "Score",
    "No other destination is within 100 km of {city}.", "{name} is more than 100 km from {other}.",
    "You can add at most {n} nearby cities.", "{name} has limited data", "{n} of {total} attractions can be planned from here.",
    "Data for this city is limited.", "km straight line", "km by road", "Five neighbourhoods, one in each part of the city, from OpenStreetMap.",
]


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
        return render_template("error.html", code=404, title=i18n.gettext("Page not found"),
                               message=i18n.gettext("We couldn't find that page or destination.")), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Unhandled error: %s", error)
        if _wants_json():
            return jsonify(error="internal server error"), 500
        return render_template("error.html", code=500, title=i18n.gettext("Something went wrong"),
                               message=i18n.gettext("An unexpected error occurred. Please try again in a moment.")), 500


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
