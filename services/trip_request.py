"""Server-side validation: query parameters -> TripRequest, or field errors.

Never trust the browser: every value is re-checked here even though the HTML
form already has min/max/required hints. Missing optional fields get sensible
defaults, so a short URL like /itinerary?city=delhi&days=2 also works.
"""

from datetime import date

import config
from services.models import TripRequest
from services.timeutil import fmt_hhmm, parse_hhmm

TRUE_VALUES = {"on", "1", "true", "yes"}


def _clean(value):
    return (value or "").strip()


def _getlist(args, key):
    """All values of a repeated parameter (works for MultiDict and plain dicts)."""
    if hasattr(args, "getlist"):
        return args.getlist(key)
    value = args.get(key)
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def parse_trip(args, load_city, category_slugs, today=None):
    """Validate request arguments.

    args:           a werkzeug MultiDict (request.args) or a plain dict
    load_city:      function(slug) -> CityData or None
    category_slugs: set of known interest/category slugs

    Returns (trip or None, errors {field: message}, values {field: str} for re-filling the form).
    """
    today = today or date.today()
    errors, values = {}, {}

    # City ---------------------------------------------------------------
    city_slug = _clean(args.get("city"))
    values["city"] = city_slug
    city = load_city(city_slug) if city_slug else None
    if not city_slug:
        errors["city"] = "Choose a destination city."
    elif city is None:
        errors["city"] = "We don't have data for that city yet."

    # Start date -----------------------------------------------------------
    raw = _clean(args.get("start_date")) or today.isoformat()
    values["start_date"] = raw
    try:
        start_date = date.fromisoformat(raw)
    except ValueError:
        start_date = None
        errors["start_date"] = "Enter a date as YYYY-MM-DD."

    # Days -----------------------------------------------------------------
    raw = _clean(args.get("days")) or "1"
    values["days"] = raw
    days = None
    if not raw.isdigit():
        errors["days"] = f"Number of days must be a whole number from 1 to {config.MAX_DAYS}."
    else:
        days = int(raw)
        if not 1 <= days <= config.MAX_DAYS:
            errors["days"] = f"Plan between 1 and {config.MAX_DAYS} days."

    # Daily time window ------------------------------------------------------
    day_start = day_end = None
    for key, default in (("day_start", config.DEFAULT_DAY_START), ("day_end", config.DEFAULT_DAY_END)):
        raw = _clean(args.get(key)) or default
        values[key] = raw
        try:
            minutes = parse_hhmm(raw)
        except ValueError:
            errors[key] = "Enter a time as HH:MM (24-hour)."
            continue
        if key == "day_start":
            day_start = minutes
        else:
            day_end = minutes
    if day_start is not None and day_end is not None and day_end - day_start < config.MIN_DAY_LENGTH_MIN:
        errors["day_end"] = (f"Your day must end at least {config.MIN_DAY_LENGTH_MIN // 60} hours after it starts "
                             f"(after {fmt_hhmm(day_start + config.MIN_DAY_LENGTH_MIN)}).")

    # Budget -----------------------------------------------------------------
    raw = _clean(args.get("budget")).replace(",", "").replace("₹", "")
    values["budget"] = raw
    budget = None
    if raw:
        try:
            budget = int(float(raw))
            if float(raw) != budget:
                raise ValueError
        except ValueError:
            errors["budget"] = "Budget must be a whole number of rupees, or leave it empty for no limit."
            budget = None
        else:
            if budget < 0:
                errors["budget"] = "Budget cannot be negative."
            elif budget > config.MAX_BUDGET_INR:
                errors["budget"] = f"Budget must be at most ₹{config.MAX_BUDGET_INR:,}."
    include_transport = _clean(args.get("transport")).lower() in TRUE_VALUES
    values["transport"] = "on" if include_transport else ""

    # Interests --------------------------------------------------------------
    interests = []
    for raw in _getlist(args, "interests"):
        for part in raw.split(","):
            part = part.strip()
            if part and part not in interests:
                interests.append(part)
    values["interests"] = interests
    unknown = [i for i in interests if i not in category_slugs]
    if unknown:
        errors["interests"] = f"Unknown interest: {', '.join(unknown)}."

    # Pace and strategy -------------------------------------------------------
    pace = _clean(args.get("pace")) or config.DEFAULT_PACE
    values["pace"] = pace
    if pace not in config.PACES:
        errors["pace"] = "Choose relaxed, balanced or packed."
    strategy = _clean(args.get("strategy")) or config.DEFAULT_STRATEGY
    values["strategy"] = strategy
    if strategy not in config.STRATEGIES:
        errors["strategy"] = "Unknown selection strategy."

    # Start point and exclusions (need a valid city) ----------------------------
    start = _clean(args.get("start"))
    exclude = []
    for raw in _getlist(args, "exclude"):
        exclude.extend(p.strip() for p in raw.split(",") if p.strip())
    exclude = sorted(set(exclude))
    values["exclude"] = exclude
    if city is not None:
        if not start:
            start = city.start_points[0].slug if city.start_points else ""
        if city.place(start) is None:
            errors["start"] = "Choose a starting point in this city."
        bad = [s for s in exclude if city.attraction_by_slug(s) is None]
        if bad:
            errors["exclude"] = f"Not an attraction in {city.name}: {', '.join(bad)}."
        elif exclude and len(exclude) >= len(city.attractions):
            errors["exclude"] = "Keep at least one attraction in the plan."
    values["start"] = start

    if errors:
        return None, errors, values
    trip = TripRequest(city=city_slug, start_date=start_date, days=days, day_start=day_start, day_end=day_end,
                       budget=budget, include_transport=include_transport, interests=tuple(interests),
                       pace=pace, start=start, strategy=strategy, exclude=tuple(exclude))
    return trip, {}, values
