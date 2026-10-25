"""Server-side validation: query parameters -> TripRequest, or field errors.

Never trust the browser: every value is re-checked here even though the HTML
form already has min/max/required hints. Missing optional fields get sensible
defaults, so a short URL like /itinerary?city=delhi&days=2 also works.

Inputs are canonicalised (interests and extra cities sorted, duplicates
removed), so the same choices always give the same TripRequest -- and
therefore the same plan -- whatever order the browser sent them in.
"""

from datetime import date, timedelta

import config
from services.models import MealSetting, TripRequest
from services.multicity import group_problems
from services.i18n import gettext as _
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
        errors[kind] = _("Enter the {meal} window as HH:MM (24-hour).", meal=_(kind))
        return None
    if not minutes_raw.isdigit() or not 15 <= int(minutes_raw) <= 180:
        errors[kind] = _("{meal} length must be 15 to 180 minutes.", meal=_(kind.capitalize()))
        return None
    minutes = int(minutes_raw)
    if latest_end - earliest < minutes:
        errors[kind] = _("A {minutes}-minute {meal} does not fit between {start} and {end}.", minutes=minutes,
                         meal=_(kind), start=fmt_hhmm(earliest), end=fmt_hhmm(latest_end))
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
        errors["city"] = _("Choose a destination city.")
    elif city is None:
        errors["city"] = _("We don't have data for that city yet.")

    # Nearby cities added to the trip ---------------------------------------
    extras = sorted(s for s in _split_list(args, "also") if s != city_slug)
    values["also"] = extras
    area = city
    if extras and city is not None:
        unknown = [s for s in extras if load_area((s,)) is None]
        if unknown:
            errors["also"] = _("Unknown city: {names}.", names=", ".join(unknown))
        elif len(extras) > config.MAX_EXTRA_CITIES:
            errors["also"] = _("Add at most {n} nearby cities.", n=config.MAX_EXTRA_CITIES)
        else:
            group = [city.info] + [load_area((s,)).info for s in extras]
            problems = group_problems(group)
            if problems:
                errors["also"] = " ".join(problems)
            else:
                area = load_area((city_slug,) + tuple(extras))

    # Dates ------------------------------------------------------------------
    # The trip runs from start_date to end_date, both included: 1 Oct - 5 Oct is 5 days.
    # Older links that give `days` instead of an end date still work.
    raw = _clean(args.get("start_date")) or today.isoformat()
    values["start_date"] = raw
    try:
        start_date = date.fromisoformat(raw)
    except ValueError:
        start_date = None
        errors["start_date"] = _("Enter the start date as YYYY-MM-DD.")
    raw_end = _clean(args.get("end_date"))
    raw_days = _clean(args.get("days"))
    end_date = days = None
    if raw_end:
        try:
            end_date = date.fromisoformat(raw_end)
        except ValueError:
            errors["end_date"] = _("Enter the end date as YYYY-MM-DD.")
    elif raw_days:
        if not raw_days.isdigit() or int(raw_days) < 1:
            errors["end_date"] = _("Choose an end date on or after the start date.")
        elif start_date is not None:
            end_date = start_date + timedelta(days=min(int(raw_days), config.MAX_DAYS + 1) - 1)
    elif start_date is not None:
        end_date = start_date                                  # a one-day trip
    if start_date is not None and end_date is not None:
        days = (end_date - start_date).days + 1
        if days < 1:
            errors["end_date"] = _("The end date cannot be before the start date.")
            days = None
        elif days > config.MAX_DAYS:
            errors["end_date"] = _("Trips can be up to {max} days long; this one is {days} days. Choose an earlier end date.",
                                   max=config.MAX_DAYS, days=days)
            days = None
    values["end_date"] = end_date.isoformat() if end_date else raw_end
    values["days"] = str(days) if days else ""

    # Daily time window ------------------------------------------------------
    day_start = day_end = None
    for key, default in (("day_start", config.DEFAULT_DAY_START), ("day_end", config.DEFAULT_DAY_END)):
        raw = _clean(args.get(key)) or default
        values[key] = raw
        try:
            minutes = parse_hhmm(raw)
        except ValueError:
            errors[key] = _("Enter a time as HH:MM (24-hour).")
            continue
        if key == "day_start":
            day_start = minutes
        else:
            day_end = minutes
    if day_start is not None and day_end is not None and day_end - day_start < config.MIN_DAY_LENGTH_MIN:
        errors["day_end"] = _("Your day must end at least {hours} hours after it starts (after {time}).",
                              hours=config.MIN_DAY_LENGTH_MIN // 60, time=fmt_hhmm(day_start + config.MIN_DAY_LENGTH_MIN))

    # Interests --------------------------------------------------------------
    interests = sorted(set(_split_list(args, "interests")))
    values["interests"] = interests
    unknown = [i for i in interests if i not in category_slugs]
    if unknown:
        errors["interests"] = _("Unknown interest: {names}.", names=", ".join(unknown))
    interest_mode = _clean(args.get("interest_mode")) or "prefer"
    values["interest_mode"] = interest_mode
    if interest_mode not in config.INTEREST_MODES:
        errors["interest_mode"] = _("Choose 'prefer' or 'only' for interests.")
    elif interest_mode == "only" and not interests:
        errors["interest_mode"] = _("Pick at least one interest to plan only matching places.")

    # Meals ------------------------------------------------------------------
    lunch = _parse_meal(args, "lunch", config.DEFAULT_LUNCH, errors, values)
    dinner = _parse_meal(args, "dinner", config.DEFAULT_DINNER, errors, values)
    if lunch and dinner and lunch.latest_end > dinner.earliest:
        errors["dinner"] = _("The dinner window must start after the lunch window ends.")
    food_venues = _switch(args, "venues", True)
    values["venues"] = "on" if food_venues else "off"
    venue_styles = sorted(set(_split_list(args, "venue_style")))
    values["venue_style"] = venue_styles
    bad = [s for s in venue_styles if s not in config.VENUE_STYLES]
    if bad:
        errors["venue_style"] = _("Unknown meal-venue style: {names}.", names=", ".join(bad))
    veg_only = _switch(args, "veg", False)
    values["veg"] = "on" if veg_only else ""

    # Shopping ---------------------------------------------------------------
    raw = _clean(args.get("shop_min"))
    values["shop_min"] = raw
    shop_minutes = None
    if raw:
        if not raw.isdigit() or int(raw) not in config.SHOP_MINUTES:
            errors["shop_min"] = _("Choose one of the listed shopping times.")
        else:
            shop_minutes = int(raw)

    # Pace and strategy -------------------------------------------------------
    pace = _clean(args.get("pace")) or config.DEFAULT_PACE
    values["pace"] = pace
    if pace not in config.PACES:
        errors["pace"] = _("Choose relaxed, balanced or packed.")
    strategy = _clean(args.get("strategy")) or config.DEFAULT_STRATEGY
    values["strategy"] = strategy
    if strategy not in config.STRATEGIES:
        errors["strategy"] = _("Unknown selection strategy.")
    mode = _clean(args.get("mode")) or config.DEFAULT_MODE
    values["mode"] = mode
    if mode not in config.MODES:
        errors["mode"] = _("Choose Evenly Distributed, Suggested or Most Optimized.")

    # Places to visit: empty = the planner chooses (with the strategy above).
    choose = _clean(args.get("choose")) or ("pick" if _split_list(args, "places") else "auto")
    values["choose"] = choose
    places = sorted(set(_split_list(args, "places"))) if choose == "pick" else []
    values["places"] = places
    if choose == "pick" and not places:
        errors["places"] = _("Pick at least one place to visit, or let the planner choose.")
    elif len(places) > config.MAX_PICKED_PLACES:
        errors["places"] = _("Pick at most {n} places.", n=config.MAX_PICKED_PLACES)

    # Stay area and exclusions (need a valid city) ----------------------------
    # Every day starts and ends at one of the trip's stay areas -- never at an
    # attraction or a station. Empty = the base city's central area.
    start = _clean(args.get("start"))
    exclude = sorted(set(_split_list(args, "exclude")))
    values["exclude"] = exclude
    if city is not None:
        if not start:
            start = city.stays[0].slug if city.stays else ""
        if city.stay(start) is None:
            errors["start"] = _("Choose one of the stay areas in {city}.", city=city.name)
        if area is not None:
            bad = [s for s in exclude if area.attraction_by_slug(s) is None]
            if bad:
                errors["exclude"] = _("Not an attraction in {city}: {names}.", city=area.name, names=", ".join(bad))
            elif exclude and len(exclude) >= len(area.attractions):
                errors["exclude"] = _("Keep at least one attraction in the plan.")
            bad = [s for s in places if area.attraction_by_slug(s) is None]
            if bad and "places" not in errors:
                errors["places"] = _("Not an attraction in {city}: {names}.", city=area.name, names=", ".join(bad))
            elif set(places) & set(exclude):
                errors["places"] = _("A place cannot be both picked and excluded.")

    # Where the trip ends, and whether the stay moves with you ---------------------
    # "move": sleep in each city in turn (one-way, or a round trip back to the start);
    # "base": one stay, day trips. A link that does not say falls back to "base" when
    # the trip is too short to move between its cities.
    asked = _clean(args.get("overnight"))
    overnight = asked or "move"
    if overnight not in ("move", "base"):
        errors["overnight"] = _("Choose whether your stay moves with you or stays in one base.")
    end = _clean(args.get("end"))
    if end == start or overnight == "base":
        end = ""
    if end and area is not None and "start" not in errors:
        place = area.place(end)
        if place is None or place.kind != "stay" or place.city_slug not in area.city_slugs:
            errors["end"] = _("Choose the stay area of your last night in one of the trip's cities.")
    if overnight == "move" and area is not None and days is not None and not ({"start", "end"} & set(errors)):
        end_city = area.place(end).city_slug if end else city_slug
        others = [s for s in area.city_slugs if s not in (city_slug, end_city)]
        stops = 1 + len(others) + (1 if (end or others) else 0)
        if stops > 1 and days < stops - 1:
            if asked:
                errors["end"] = _("A trip through {stops} stays needs at least {days} days (one for each move): choose a later "
                                  "end date, or one base with day trips.", stops=stops, days=stops - 1)
            else:
                overnight, end = "base", ""
    values["overnight"] = overnight
    values["end"] = end
    values["start"] = start

    if errors:
        return None, errors, values
    trip = TripRequest(city=city_slug, start_date=start_date, days=days, day_start=day_start, day_end=day_end,
                       interests=tuple(interests),
                       pace=pace, start=start, strategy=strategy, exclude=tuple(exclude),
                       extra_cities=tuple(extras), interest_mode=interest_mode, lunch=lunch, dinner=dinner,
                       food_venues=food_venues, venue_styles=tuple(venue_styles), veg_only=veg_only,
                       shop_minutes=shop_minutes, mode=mode, places=tuple(places), end=end, overnight=overnight)
    return trip, {}, values
