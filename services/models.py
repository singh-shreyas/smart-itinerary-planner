"""Data shapes shared by the planner, the validator, the routes and the templates.

Totals on DayPlan and Itinerary are computed properties, so they can never
drift away from the visits and legs they summarise (no double counting).
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


@dataclass
class Attraction:
    id: int
    slug: str
    name: str
    lat: float
    lng: float
    rating: float
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


@dataclass(frozen=True)
class TripRequest:
    """A validated trip. Built only by services.trip_request.parse_trip."""
    city: str
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
        }
        if trip.include_transport:
            query["transport"] = "on"
        if trip.exclude:
            query["exclude"] = ",".join(trip.exclude)
        return query


@dataclass
class Leg:
    """Travel between two places along the shortest path found by Dijkstra."""
    from_id: int
    to_id: int
    minutes: int
    km: float
    via: list = field(default_factory=list)      # names of intermediate places on the path


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

    @property
    def weekday(self):
        return self.date.weekday()

    @property
    def legs(self):
        legs = [v.leg for v in self.visits]
        if self.return_leg is not None:
            legs.append(self.return_leg)
        return legs

    @property
    def return_time(self):
        if not self.visits:
            return None
        return self.visits[-1].leave + self.return_leg.minutes

    @property
    def travel_min(self):
        return sum(leg.minutes for leg in self.legs)

    @property
    def km(self):
        return round(sum(leg.km for leg in self.legs), 1)

    @property
    def sight_min(self):
        return sum(v.attraction.visit_min for v in self.visits)

    @property
    def wait_min(self):
        return sum(v.wait for v in self.visits)

    @property
    def buffer_min(self):
        return sum(v.buffer for v in self.visits)

    @property
    def fees(self):
        return sum(v.attraction.fee for v in self.visits)

    @property
    def transport_cost(self):
        return int(round(self.km * self.transport_rate))

    @property
    def score(self):
        return sum(v.score for v in self.visits)

    def spend(self, include_transport):
        return self.fees + (self.transport_cost if include_transport else 0)


@dataclass
class Skipped:
    attraction: Attraction
    code: str                 # excluded / unreachable / closed / over_budget / does_not_fit / not_selected
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

    @property
    def visits(self):
        return [v for day in self.days for v in day.visits]

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
    def km(self):
        return round(sum(day.km for day in self.days), 1)

    @property
    def sight_min(self):
        return sum(day.sight_min for day in self.days)

    @property
    def wait_min(self):
        return sum(day.wait_min for day in self.days)

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
