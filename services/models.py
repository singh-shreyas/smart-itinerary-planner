"""Data shapes shared by the planner, the validator, the routes and the templates.

Totals on DayPlan and Itinerary are computed properties, so they can never
drift away from the visits, meals and legs they summarise (no double counting).
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from services.timeutil import WEEKDAY_SHORT, fmt_hhmm


@dataclass(frozen=True)
class Window:
    """One opening window on one weekday, in minutes after midnight."""
    open_min: int
    close_min: int
    last_entry_min: int | None = None

    def latest_start(self, visit_min):
        """Latest moment a visit of visit_min minutes may start in this window."""
        latest = self.close_min - visit_min
        if self.last_entry_min is not None:
            latest = min(latest, self.last_entry_min)
        return latest

    def label(self):
        text = f"{fmt_hhmm(self.open_min)}–{fmt_hhmm(self.close_min)}"
        if self.last_entry_min is not None:
            text += f" (last entry {fmt_hhmm(self.last_entry_min)})"
        return text


@dataclass
class Place:
    id: int
    slug: str
    name: str
    kind: str
    lat: float
    lng: float
    city_slug: str = ""
    city_name: str = ""
    access: str = "road"
    access_note: str | None = None


@dataclass
class Attraction:
    id: int
    slug: str
    name: str
    lat: float
    lng: float
    rating: float | None                 # None = no rating data (never invented)
    popularity: float
    visit_min: int
    fee: int
    categories: tuple
    hours: dict                          # weekday (0 = Monday) -> [Window, ...] sorted by opening
    description: str = ""
    image: str | None = None
    image_credit: str | None = None
    image_source_url: str | None = None
    info_url: str | None = None
    data_status: str = "illustrative"
    in_team_catalog: bool = False
    city_slug: str = ""
    city_name: str = ""
    # Where each value came from (see database/schema.sql)
    rating_source: str = "illustrative"
    popularity_source: str = "illustrative"
    duration_source: str = "illustrative"
    fee_source: str = "illustrative"
    hours_source: str = "illustrative"
    coord_source: str | None = None
    description_source: str | None = None
    pageviews: int | None = None
    wikidata: str | None = None
    place_type: str | None = None
    cuisine: tuple = ()                  # meal-venue styles (food places only)
    vegetarian: str = "unknown"
    access: str = "road"
    access_note: str | None = None
    kinds: frozenset = frozenset()       # {'sight', 'food', 'shopping'} from its categories

    def windows_on(self, weekday):
        return self.hours.get(weekday, [])

    def open_weekdays(self):
        return sorted(day for day, windows in self.hours.items() if windows)

    def closing_time_on(self, weekday):
        windows = self.windows_on(weekday)
        return max(w.close_min for w in windows) if windows else None

    def hours_label(self, weekday):
        windows = self.windows_on(weekday)
        if not windows:
            return f"Closed {WEEKDAY_SHORT[weekday]}"
        return ", ".join(f"{fmt_hhmm(w.open_min)}–{fmt_hhmm(w.close_min)}" for w in windows)

    @property
    def rated(self):
        return self.rating is not None

    @property
    def is_food_or_shopping_only(self):
        """Food and shopping places are optional: planned only when the traveller asks for them."""
        return bool(self.kinds) and "sight" not in self.kinds

    @property
    def is_food(self):
        return "food" in self.kinds

    @property
    def is_shopping_only(self):
        return self.kinds == frozenset({"shopping"})


@dataclass(frozen=True)
class MealSetting:
    """A meal the traveller wants: it must start no earlier than `earliest`, end by `latest_end`."""
    kind: str             # 'lunch' or 'dinner'
    earliest: int
    latest_end: int
    minutes: int

    @property
    def latest_start(self):
        return self.latest_end - self.minutes

    @property
    def label(self):
        return self.kind.capitalize()

    def needed(self, day_start, day_end):
        """Plan this meal only if it cannot be had entirely before the day starts or after it ends."""
        before = day_start >= self.earliest + self.minutes
        after = day_end <= self.latest_start
        return not before and not after


@dataclass(frozen=True)
class TripRequest:
    """A validated trip. Built only by services.trip_request.parse_trip.

    The defaults below are the "nothing extra" settings used by the unit tests;
    the web form starts with lunch and dinner switched on.
    """
    city: str                            # base city: every day starts and ends here
    start_date: date
    days: int
    day_start: int
    day_end: int
    budget: int | None
    include_transport: bool
    interests: tuple
    pace: str
    start: str
    strategy: str
    exclude: tuple = ()
    extra_cities: tuple = ()             # nearby cities added to the trip (sorted)
    interest_mode: str = "prefer"
    lunch: MealSetting | None = None
    dinner: MealSetting | None = None
    food_venues: bool = True             # send meals to listed food places when one is close
    venue_styles: tuple = ()             # preferred meal-venue styles
    veg_only: bool = False
    shop_minutes: int | None = None      # time per shopping stop (None = the place's own estimate)
    shop_spend: int = 0                  # planned spend per shopping stop, counted in the budget

    @property
    def city_slugs(self):
        return (self.city,) + tuple(self.extra_cities)

    @property
    def meals(self):
        return [m for m in (self.lunch, self.dinner) if m is not None]

    def dates(self):
        return [self.start_date + timedelta(days=i) for i in range(self.days)]

    def with_changes(self, **changes):
        return replace(self, **changes)

    def to_query(self, **overrides):
        """URL parameters that reproduce this trip (plans are a pure function of the URL)."""
        trip = self.with_changes(**overrides) if overrides else self
        query = {
            "city": trip.city,
            "start_date": trip.start_date.isoformat(),
            "days": trip.days,
            "day_start": fmt_hhmm(trip.day_start),
            "day_end": fmt_hhmm(trip.day_end),
            "budget": "" if trip.budget is None else trip.budget,
            "pace": trip.pace,
            "start": trip.start,
            "strategy": trip.strategy,
            "interests": list(trip.interests),
            "interest_mode": trip.interest_mode,
            "lunch": "on" if trip.lunch else "off",
            "dinner": "on" if trip.dinner else "off",
            "venues": "on" if trip.food_venues else "off",
        }
        for meal in trip.meals:
            prefix = meal.kind
            query[f"{prefix}_from"] = fmt_hhmm(meal.earliest)
            query[f"{prefix}_to"] = fmt_hhmm(meal.latest_end)
            query[f"{prefix}_min"] = meal.minutes
        if trip.include_transport:
            query["transport"] = "on"
        if trip.exclude:
            query["exclude"] = ",".join(trip.exclude)
        if trip.extra_cities:
            query["also"] = ",".join(trip.extra_cities)
        if trip.venue_styles:
            query["venue_style"] = list(trip.venue_styles)
        if trip.veg_only:
            query["veg"] = "on"
        if trip.shop_minutes:
            query["shop_min"] = trip.shop_minutes
        if trip.shop_spend:
            query["shop_spend"] = trip.shop_spend
        return query


@dataclass
class Leg:
    """Travel between two places along the shortest path found by Dijkstra.

    minutes      planned minutes (raw estimate rounded UP to 10) -- used by the schedule
    raw_minutes  road estimate before rounding (OSRM free-flow x traffic factor)
    """
    from_id: int
    to_id: int
    minutes: int
    km: float
    via: list = field(default_factory=list)      # names of intermediate places on the path
    raw_minutes: int | None = None
    intercity: bool = False                      # from and to are in different cities
    estimated: bool = False                      # the path uses a straight-line estimate, not road data
    depart: int | None = None                    # clock time the leg starts
    purpose: str = "travel"                      # 'travel' or 'meal' (a detour to a food place)

    @property
    def arrive(self):
        return None if self.depart is None else self.depart + self.minutes


@dataclass
class Visit:
    attraction: Attraction
    leg: Leg                  # the leg that brought us here
    arrive: int
    start: int
    end: int
    leave: int
    score: int

    @property
    def wait(self):
        return self.start - self.arrive

    @property
    def buffer(self):
        return self.leave - self.end

    @property
    def duration(self):
        return self.end - self.start


@dataclass
class MealBreak:
    """Lunch or dinner as its own timeline entry (never a sightseeing stop).

    venue      a listed food place (Attraction) when one was close enough, else None
    leg        the detour to the venue (None when eating where you already are)
    at_base    True when the meal is taken near the start point after returning
    """
    kind: str
    setting: MealSetting
    location_id: int
    location_name: str
    arrive: int
    start: int
    end: int
    venue: Attraction | None = None
    leg: Leg | None = None
    at_base: bool = False

    @property
    def leave(self):
        return self.end

    @property
    def wait(self):
        return 0 if self.at_base else self.start - self.arrive

    @property
    def label(self):
        return self.setting.label


@dataclass
class DayPlan:
    index: int                               # 1-based day number
    date: date
    depart: int                              # time the traveller leaves the start point
    visits: list
    return_leg: Leg | None
    transport_rate: float                    # Rs per km used for the transport estimate
    branch: str = ""                         # routing branch that produced this order
    empty_reason: str | None = None
    suggestions: list = field(default_factory=list)
    meals: list = field(default_factory=list)
    timeline: list = field(default_factory=list)   # Visit and MealBreak entries in time order
    day_start: int = 0
    day_end: int = 0
    shop_spend: int = 0                      # planned spend per shopping stop
    focus: str = ""                          # which city (or cities) the day was planned around
    free_time_notes: list = field(default_factory=list)
    filled: list = field(default_factory=list)     # attraction ids added by the fill step

    @property
    def weekday(self):
        return self.date.weekday()

    @property
    def legs(self):
        legs = [v.leg for v in self.visits]
        legs += [m.leg for m in self.meals if m.leg is not None]
        if self.return_leg is not None:
            legs.append(self.return_leg)
        return legs

    @property
    def return_time(self):
        if not self.visits:
            return None
        return self.return_leg.depart + self.return_leg.minutes

    @property
    def end_time(self):
        """When the last activity of the day ends (the return, or a dinner near the base)."""
        if not self.visits:
            return None
        return max([self.return_time] + [m.end for m in self.meals])

    @property
    def window_min(self):
        return self.day_end - self.day_start

    @property
    def travel_min(self):
        return sum(leg.minutes for leg in self.legs)

    @property
    def intercity_min(self):
        return sum(leg.minutes for leg in self.legs if leg.intercity)

    @property
    def local_travel_min(self):
        return self.travel_min - self.intercity_min

    @property
    def raw_travel_min(self):
        return sum(leg.raw_minutes or 0 for leg in self.legs)

    @property
    def km_exact(self):
        return sum(leg.km for leg in self.legs)

    @property
    def km(self):
        return round(self.km_exact, 1)

    @property
    def sight_min(self):
        return sum(v.duration for v in self.visits)

    @property
    def meal_min(self):
        return sum(m.end - m.start for m in self.meals)

    @property
    def wait_min(self):
        return sum(v.wait for v in self.visits) + sum(m.wait for m in self.meals)

    @property
    def buffer_min(self):
        return sum(v.buffer for v in self.visits)

    @property
    def free_min(self):
        """Time in the day window that is not used by anything above."""
        if not self.visits:
            return self.window_min
        used = self.travel_min + self.sight_min + self.meal_min + self.wait_min + self.buffer_min
        return self.window_min - used

    @property
    def free_after_min(self):
        return 0 if not self.visits else self.day_end - self.end_time

    @property
    def fees(self):
        return sum(v.attraction.fee for v in self.visits)

    @property
    def shopping_spend(self):
        return self.shop_spend * sum(1 for v in self.visits if v.attraction.is_shopping_only)

    @property
    def transport_cost(self):
        return int(round(self.km_exact * self.transport_rate))

    @property
    def score(self):
        return sum(v.score for v in self.visits)

    def spend(self, include_transport):
        return self.fees + self.shopping_spend + (self.transport_cost if include_transport else 0)


@dataclass
class Skipped:
    attraction: Attraction
    code: str                 # excluded / unreachable / no_road / closed / over_budget / does_not_fit / not_selected / opt_in / interest
    reason: str               # one-line explanation shown to the user
    details: list = field(default_factory=list)


@dataclass
class Itinerary:
    trip: TripRequest
    city_name: str
    start_place: Place
    days: list
    skipped: list
    runtime_ms: float = 0.0
    violations: list = field(default_factory=list)
    cities: list = field(default_factory=list)          # [{slug, name, ...}] base city first
    estimated_links: list = field(default_factory=list)  # city pairs joined by a straight-line estimate
    interest_notes: list = field(default_factory=list)   # interests with no / little data in these cities
    versions: dict = field(default_factory=dict)         # data / config / plan fingerprints

    @property
    def visits(self):
        return [v for day in self.days for v in day.visits]

    @property
    def meals(self):
        return [m for day in self.days for m in day.meals]

    @property
    def stops(self):
        return len(self.visits)

    @property
    def score(self):
        return sum(day.score for day in self.days)

    @property
    def travel_min(self):
        return sum(day.travel_min for day in self.days)

    @property
    def intercity_min(self):
        return sum(day.intercity_min for day in self.days)

    @property
    def km(self):
        return round(sum(day.km for day in self.days), 1)

    @property
    def sight_min(self):
        return sum(day.sight_min for day in self.days)

    @property
    def meal_min(self):
        return sum(day.meal_min for day in self.days)

    @property
    def wait_min(self):
        return sum(day.wait_min for day in self.days)

    @property
    def buffer_min(self):
        return sum(day.buffer_min for day in self.days)

    @property
    def free_min(self):
        return sum(day.free_min for day in self.days)

    @property
    def available_min(self):
        return sum(day.window_min for day in self.days)

    @property
    def fees(self):
        return sum(day.fees for day in self.days)

    @property
    def transport_cost(self):
        return sum(day.transport_cost for day in self.days)

    @property
    def spend(self):
        return sum(day.spend(self.trip.include_transport) for day in self.days)

    @property
    def illustrative(self):
        return any(v.attraction.data_status != "verified" for v in self.visits)

    @property
    def multi_city(self):
        return len(self.cities) > 1
