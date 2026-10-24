"""Server-side validation: query parameters -> TripRequest, or field errors.

Never trust the browser: every value is re-checked here even though the HTML
form already has min/max/required hints. Missing optional fields get sensible
defaults, so a short URL like /itinerary?city=delhi&days=2 also works.

Inputs are canonicalised (interests and extra cities sorted, duplicates
removed), so the same choices always give the same TripRequest -- and
therefore the same plan -- whatever order the browser sent them in.
"""

from datetime import date

import config
from services.models import MealSetting, TripRequest
from services.multicity import group_problems
from services.timeutil import fmt_hhmm, parse_hhmm

TRUE_VALUES = {"on", "1", "true", "yes"}
FALSE_VALUES = {"off", "0", "false", "no"}


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


def _switch(args, key, default):
    """A checkbox that may be preceded by a hidden 'off' field: the LAST value wins; absent = default."""
    values = [_clean(v).lower() for v in _getlist(args, key) if _clean(v)]
    if not values:
        return default
    return values[-1] in TRUE_VALUES


def _split_list(args, key):
    items = []
    for raw in _getlist(args, key):
        for part in str(raw).split(","):
            part = part.strip()
            if part and part not in items:
                items.append(part)
    return items


def _parse_meal(args, kind, default, errors, values):
    enabled = _switch(args, kind, True)
    values[kind] = "on" if enabled else "off"
    start_raw = _clean(args.get(f"{kind}_from")) or default[0]
    end_raw = _clean(args.get(f"{kind}_to")) or default[1]
    minutes_raw = _clean(args.get(f"{kind}_min")) or str(default[2])
    values.update({f"{kind}_from": start_raw, f"{kind}_to": end_raw, f"{kind}_min": minutes_raw})
    if not enabled:
        return None
    try:
        earliest, latest_end = parse_hhmm(start_raw), parse_hhmm(end_raw)
    except ValueError:
        errors[kind] = f"Enter the {kind} window as HH:MM (24-hour)."
        return None
    if not minutes_raw.isdigit() or not 15 <= int(minutes_raw) <= 180:
        errors[kind] = f"{kind.capitalize()} length must be 15 to 180 minutes."
        return None
    minutes = int(minutes_raw)
    if latest_end - earliest < minutes:
        errors[kind] = (f"A {minutes}-minute {kind} does not fit between {fmt_hhmm(earliest)} "
                        f"and {fmt_hhmm(latest_end)}.")
        return None
    return MealSetting(kind, earliest, latest_end, minutes)


def parse_trip(args, load_area, category_slugs, today=None, all_cities=None):
    """Validate request arguments.

    args:           a werkzeug MultiDict (request.args) or a plain dict
    load_area:      function(tuple of city slugs) -> CityData or None
    category_slugs: set of known interest/category slugs
    all_cities:     optional {slug: city row} used to check multi-city distances

    Returns (trip or None, errors {field: message}, values {field: ...} for re-filling the form).
    """
    today = today or date.today()
    errors, values = {}, {}

    # City ---------------------------------------------------------------
    city_slug = _clean(args.get("city"))
    values["city"] = city_slug
    city = load_area((city_slug,)) if city_slug else None
    if not city_slug:
        errors["city"] = "Choose a destination city."
    elif city is None:
        errors["city"] = "We don't have data for that city yet."

    # Nearby cities added to the trip ---------------------------------------
    extras = sorted(s for s in _split_list(args, "also") if s != city_slug)
    values["also"] = extras
    area = city
    if extras and city is not None:
        unknown = [s for s in extras if load_area((s,)) is None]
        if unknown:
            errors["also"] = f"Unknown city: {', '.join(unknown)}."
        elif len(extras) > config.MAX_EXTRA_CITIES:
            errors["also"] = f"Add at most {config.MAX_EXTRA_CITIES} nearby cities."
        else:
            group = [city.info] + [load_area((s,)).info for s in extras]
            problems = group_problems(group)
            if problems:
                errors["also"] = " ".join(problems)
            else:
                area = load_area((city_slug,) + tuple(extras))

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
    include_transport = _switch(args, "transport", False)
    values["transport"] = "on" if include_transport else ""

    # Interests --------------------------------------------------------------
    interests = sorted(set(_split_list(args, "interests")))
    values["interests"] = interests
    unknown = [i for i in interests if i not in category_slugs]
    if unknown:
        errors["interests"] = f"Unknown interest: {', '.join(unknown)}."
    interest_mode = _clean(args.get("interest_mode")) or "prefer"
    values["interest_mode"] = interest_mode
    if interest_mode not in config.INTEREST_MODES:
        errors["interest_mode"] = "Choose 'prefer' or 'only' for interests."
    elif interest_mode == "only" and not interests:
        errors["interest_mode"] = "Pick at least one interest to plan only matching places."

    # Meals ------------------------------------------------------------------
    lunch = _parse_meal(args, "lunch", config.DEFAULT_LUNCH, errors, values)
    dinner = _parse_meal(args, "dinner", config.DEFAULT_DINNER, errors, values)
    if lunch and dinner and lunch.latest_end > dinner.earliest:
        errors["dinner"] = "The dinner window must start after the lunch window ends."
    food_venues = _switch(args, "venues", True)
    values["venues"] = "on" if food_venues else "off"
    venue_styles = sorted(set(_split_list(args, "venue_style")))
    values["venue_style"] = venue_styles
    bad = [s for s in venue_styles if s not in config.VENUE_STYLES]
    if bad:
        errors["venue_style"] = f"Unknown meal-venue style: {', '.join(bad)}."
    veg_only = _switch(args, "veg", False)
    values["veg"] = "on" if veg_only else ""

    # Shopping ---------------------------------------------------------------
    raw = _clean(args.get("shop_min"))
    values["shop_min"] = raw
    shop_minutes = None
    if raw:
        if not raw.isdigit() or int(raw) not in config.SHOP_MINUTES:
            errors["shop_min"] = "Choose one of the listed shopping times."
        else:
            shop_minutes = int(raw)
    raw = _clean(args.get("shop_spend")).replace(",", "").replace("₹", "")
    values["shop_spend"] = raw
    shop_spend = 0
    if raw:
        if not raw.isdigit() or int(raw) > config.MAX_SHOP_SPEND_INR:
            errors["shop_spend"] = f"Shopping spend must be a whole number from 0 to ₹{config.MAX_SHOP_SPEND_INR:,}."
        else:
            shop_spend = int(raw)

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
    exclude = sorted(set(_split_list(args, "exclude")))
    values["exclude"] = exclude
    if city is not None:
        if not start:
            start = city.start_points[0].slug if city.start_points else ""
        if city.place(start) is None:
            errors["start"] = "Choose a starting point in your base city."
        if area is not None:
            bad = [s for s in exclude if area.attraction_by_slug(s) is None]
            if bad:
                errors["exclude"] = f"Not an attraction in {area.name}: {', '.join(bad)}."
            elif exclude and len(exclude) >= len(area.attractions):
                errors["exclude"] = "Keep at least one attraction in the plan."
    values["start"] = start

    if errors:
        return None, errors, values
    trip = TripRequest(city=city_slug, start_date=start_date, days=days, day_start=day_start, day_end=day_end,
                       budget=budget, include_transport=include_transport, interests=tuple(interests),
                       pace=pace, start=start, strategy=strategy, exclude=tuple(exclude),
                       extra_cities=tuple(extras), interest_mode=interest_mode, lunch=lunch, dinner=dinner,
                       food_venues=food_venues, venue_styles=tuple(venue_styles), veg_only=veg_only,
                       shop_minutes=shop_minutes, shop_spend=shop_spend)
    return trip, {}, values
