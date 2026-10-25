"""Central configuration.

Every tunable number used by the planner lives here (score weights, pace
settings, DP discretisation, traffic factor, ...), so nothing is hidden inside
the algorithm code and each value can be explained in the viva.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # --- Flask / storage -------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret")
    DATABASE = os.path.join(BASE_DIR, "instance", "itinerary.db")
    DATA_DIR = os.path.join(BASE_DIR, "data")
    RESULTS_DIR = os.path.join(BASE_DIR, "results")
    # Build the SQLite database from the CSV files on start-up if it is missing.
    AUTO_SEED = True

    # --- Travel model ----------------------------------------------------
    # OSRM gives free-flow driving minutes (no traffic). We multiply them by a
    # single assumed traffic factor. This is an ASSUMPTION, not a calibrated
    # value, and it is shown on the About page.
    TRAFFIC_FACTOR = 1.5
    # Before replacing the database, the old file is copied to instance/backups/.
    # Only the newest few copies are kept.
    DB_BACKUPS_KEPT = 5


# --- Trip input limits (used by server-side validation) -------------------
# The trip length comes from the start and end dates (both included). There is
# no fixed five-day limit; this cap exists only because the itinerary-mode search
# and the result page grow with the number of days. Raise it if you need longer trips.
MAX_DAYS = 30
MIN_DAY_LENGTH_MIN = 120          # day end must be at least 2 hours after start
DEFAULT_DAY_START = "09:00"
DEFAULT_DAY_END = "19:00"
DEFAULT_PACE = "balanced"
DEFAULT_STRATEGY = "dp"

# --- Scoring ---------------------------------------------------------------
# score = round(100 * (W_RATING * rating/5 + W_POPULARITY * popularity + W_INTEREST * match))
# A documented design choice; the three weights sum to 1 so scores are 0..100.
W_RATING = 0.5
W_POPULARITY = 0.3
W_INTEREST = 0.2
# No free, open source of visitor ratings exists, so most attractions in the 46
# newer cities have no rating. They are scored with this neutral prior instead
# (shown as "not rated" in the interface), never with an invented rating.
RATING_PRIOR = 4.0
# Interests: "prefer" only raises the score of matching places; "only" also
# removes places that match none of the chosen interests.
INTEREST_MODES = {"prefer": "Prefer matching places", "only": "Only matching places"}

# --- Travel time display and planning ------------------------------------
# Road times are estimates, so planned travel legs are rounded UP to the next
# 10 minutes (14 -> 20, 20 -> 20, 0 -> 0). The timeline, the feasibility checks
# and the validator all use the rounded value; the raw minutes are kept for
# route optimisation and shown only as "raw estimate".
TRAVEL_ROUNDING_MIN = 10

# --- Multi-city trips -----------------------------------------------------
# A trip may add nearby cities to its base city. Rule (pairwise): EVERY pair of
# selected cities must be within MULTI_CITY_MAX_KM of each other, measured as
# the straight-line (great-circle) distance between the city centres. Straight
# line is a proxy only; real road distance is longer and is shown when known.
MULTI_CITY_MAX_KM = 100
MAX_EXTRA_CITIES = 3
# If two selected cities have no road connection in our data, the planner uses
# a clearly labelled straight-line estimate instead (never zero):
#   minutes = km * DETOUR / SPEED * 60
ESTIMATE_DETOUR_FACTOR = 1.35
ESTIMATE_SPEED_KMH = 40
WALK_SPEED_KMH = 4                 # walking pace for short last-mile walks (an assumption, labelled as one)

# --- Meals ------------------------------------------------------------------
# Defaults for the lunch and dinner breaks: (earliest start, latest end, minutes).
# A meal is planned only when it cannot be had entirely before the day starts
# or after it ends, so a short day never gets an unnecessary dinner.
DEFAULT_LUNCH = ("12:00", "14:30", 45)
DEFAULT_DINNER = ("19:00", "21:30", 60)
MEAL_DURATIONS = (30, 45, 60, 75, 90)
# A meal goes to a listed food place only if it is at most this many planned
# minutes from where you are; otherwise it is a generic break on the spot.
MEAL_VENUE_MAX_DETOUR_MIN = 20

# --- Food and shopping ------------------------------------------------------
# Kinds of meal venue a traveller can prefer (matched against data/food tags).
VENUE_STYLES = {
    "street-food": "Street food",
    "cafe-bakery": "Cafes & bakeries",
    "casual": "Casual restaurants",
    "fine-dining": "Fine dining",
    "local-specialty": "Local specialities",
}
SHOP_MINUTES = (30, 45, 60, 90, 120)       # time choices per shopping stop

# --- Pace --------------------------------------------------------------------
# Buffer minutes added after every visit (rest, photos, food, finding the exit).
PACES = {
    "relaxed": {"label": "Relaxed", "buffer": 30,
                "hint": "30 min breathing room after every stop"},
    "balanced": {"label": "Balanced", "buffer": 15,
                 "hint": "15 min after every stop"},
    "packed": {"label": "Packed", "buffer": 5,
               "hint": "Only 5 min between stops, fit in the most"},
}

# --- Selection strategies ---------------------------------------------------
# All three solve the SAME per-day knapsack instance and go through the same
# routing, scheduling, repair and validation; only the objective differs.
STRATEGIES = {
    "dp": "Dynamic programming (best total value)",
    "greedy": "Greedy (best value per minute)",
    "max_visits": "Max visits (most stops)",
}
STRATEGY_SHORT = {"dp": "DP", "greedy": "Greedy", "max_visits": "Max visits"}
STRATEGY_OBJECTIVES = {
    "dp": "Maximise the total value score. Exact (optimal) for the per-day knapsack model.",
    "greedy": "Take places in order of value per minute of the day. Fast, but can miss "
              "a better combination.",
    "max_visits": "Maximise the number of visits; among equally long lists, the higher total "
                  "value wins. Exact for the per-day knapsack model.",
}

# --- Dynamic programming discretisation ------------------------------------
# Item weights are rounded UP to 10-minute units and the capacity rounded DOWN,
# so any set the DP accepts really fits.
DP_TIME_UNIT_MIN = 10

# --- Comparison page ------------------------------------------------------
HELD_KARP_MAX_STOPS = 10          # 2^k * k^2 grows fast; exact tour only for small days
TIMING_REPEATS = 5                # median of N timed runs after one warm-up
QUALITY_LAMBDA = 0.2              # Q = total score - lambda * travel minutes

# Overall score of a plan on the comparison page = weighted sum of subscores.
# Each subscore is normalised against the best strategy on the same trip
# (100 = best of the three), so quantities in different units are never mixed
# directly. Runtime is reported separately and does not count: a few
# milliseconds do not change the traveller's day. Weights sum to 1.
# There is no cost component: the planner optimises travel and time, not money.
# (Until the budget feature was removed, "value per rupee" had 0.10; that share
# went half to travel, since this is a travel-optimisation system, and half to
# value, so value stays the largest single factor.)
SCORECARD_WEIGHTS = {
    "value": 0.45,        # total value score of the planned places
    "coverage": 0.20,     # number of places visited
    "travel": 0.20,       # travel minutes per place (fewer is better)
    "utilisation": 0.15,  # share of the available time spent sightseeing
}

# --- Itinerary modes (services/distribution.py) -------------------------------
# What to visit (the places you pick, or the strategy's choice) is separate
# from how it is spread over the trip, which is the mode.
MODES = {
    "evenly": {"label": "Evenly Distributed", "icon": "bi-distribute-horizontal",
               "text": "Spread attractions as evenly as possible across your selected trip days."},
    "suggested": {"label": "Suggested", "icon": "bi-stars",
                  "text": "A balanced itinerary that combines comfortable daily schedules with efficient travel."},
    "optimized": {"label": "Most Optimized", "icon": "bi-lightning",
                  "text": "Complete your selected attractions in the fewest feasible days."},
}
DEFAULT_MODE = "suggested"
MAX_PICKED_PLACES = 150           # enough for "Select all" across a city and its nearby cities
# Suggested mode. A day is comfortable when you are out for at most 70% of your
# window and never more than 8 hours. Cost of a plan, in minutes:
#   2 x minutes beyond comfortable + travel + 0.25 x deviation from the average day
#   + 60 for every active day beyond the minimum.
# So an extra day must remove at least 30 min of over-long days (or 60 min of
# travel) to be worth it. See the calibration in scripts/benchmark.py.
COMFORT_SHARE = 0.7
COMFORT_MAX_MIN = 8 * 60
SUGGESTED_OVERLOAD_WEIGHT = 2
SUGGESTED_IMBALANCE_WEIGHT = 0.25
SUGGESTED_DAY_COST = 60
SUGGESTED_TIE_MIN = 15             # Suggested plans this close in cost are treated as equally good
MODE_SEARCH_BUDGET = 6000          # distinct days routed per mode search before it settles (keeps long trips fast)

# --- Fill step --------------------------------------------------------------
# After a day's route is fixed, any leftover candidate that still fits (cheapest
# feasible insertion) is added, so extra hours are not left unused.
FILL_STEP = True
# The day summary explains unused time when at least this much is left.
EXPLAIN_FREE_MIN = 30


def fingerprint_settings():
    """Every setting that changes a plan. Hashed into the "config version" shown with
    each itinerary, so a changed plan can be traced to a changed setting."""
    return {
        "W": [W_RATING, W_POPULARITY, W_INTEREST], "prior": RATING_PRIOR, "paces": PACES,
        "dp_unit": DP_TIME_UNIT_MIN,
        "rounding": TRAVEL_ROUNDING_MIN, "multi": [MULTI_CITY_MAX_KM, ESTIMATE_DETOUR_FACTOR, ESTIMATE_SPEED_KMH], "walk": WALK_SPEED_KMH,
        "venue_detour": MEAL_VENUE_MAX_DETOUR_MIN, "fill": FILL_STEP,
        "suggested": [COMFORT_SHARE, COMFORT_MAX_MIN, SUGGESTED_OVERLOAD_WEIGHT, SUGGESTED_IMBALANCE_WEIGHT,
                      SUGGESTED_DAY_COST, SUGGESTED_TIE_MIN, MODE_SEARCH_BUDGET],
        "traffic": Config.TRAFFIC_FACTOR,
    }
