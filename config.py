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
    # Estimated local transport cost (auto-rickshaw / cab), rupees per km.
    # Illustrative value used only when the user includes transport in the budget.
    TRANSPORT_COST_PER_KM = 12
    # Before replacing the database, the old file is copied to instance/backups/.
    # Only the newest few copies are kept.
    DB_BACKUPS_KEPT = 5


# --- Trip input limits (used by server-side validation) -------------------
MAX_DAYS = 5
MIN_DAY_LENGTH_MIN = 120          # day end must be at least 2 hours after start
MAX_BUDGET_INR = 100_000
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
MAX_SHOP_SPEND_INR = 20_000

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
    "greedy": "Take places in order of value per unit of time and money. Fast, but can miss "
              "a better combination.",
    "max_visits": "Maximise the number of visits; among equally long lists, the higher total "
                  "value wins. Exact for the per-day knapsack model.",
}

# --- Dynamic programming discretisation ------------------------------------
# Item weights are rounded UP to 10-minute units and the capacity rounded DOWN,
# so any set the DP accepts really fits. Money units are max(Rs 10, budget/100)
# so the money axis never has more than ~100 cells.
DP_TIME_UNIT_MIN = 10
DP_MIN_MONEY_UNIT = 10
DP_MAX_MONEY_CELLS = 100

# --- Comparison page ------------------------------------------------------
HELD_KARP_MAX_STOPS = 10          # 2^k * k^2 grows fast; exact tour only for small days
TIMING_REPEATS = 5                # median of N timed runs after one warm-up
QUALITY_LAMBDA = 0.2              # Q = total score - lambda * travel minutes

# Overall score of a plan on the comparison page = weighted sum of subscores.
# Each subscore is normalised against the best strategy on the same trip
# (100 = best of the three), so quantities in different units are never mixed
# directly. Runtime is reported separately and does not count: a few
# milliseconds do not change the traveller's day. Weights sum to 1.
SCORECARD_WEIGHTS = {
    "value": 0.40,        # total value score of the planned places
    "coverage": 0.20,     # number of places visited
    "travel": 0.15,       # travel minutes per place (fewer is better)
    "utilisation": 0.15,  # share of the available time spent sightseeing
    "budget": 0.10,       # value per rupee spent
}

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
        "dp_unit": [DP_TIME_UNIT_MIN, DP_MIN_MONEY_UNIT, DP_MAX_MONEY_CELLS],
        "rounding": TRAVEL_ROUNDING_MIN, "multi": [MULTI_CITY_MAX_KM, ESTIMATE_DETOUR_FACTOR, ESTIMATE_SPEED_KMH],
        "venue_detour": MEAL_VENUE_MAX_DETOUR_MIN, "fill": FILL_STEP,
        "traffic": Config.TRAFFIC_FACTOR, "transport": Config.TRANSPORT_COST_PER_KM,
    }
