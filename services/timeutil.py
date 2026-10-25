"""Time helpers. The planner works in integer minutes after midnight (09:30 -> 570).

Two different kinds of time are kept apart on purpose:

  * CLOCK times (09:30, opening hours, the user's day window) are exact and are
    never rounded;
  * travel DURATIONS are road estimates, so a planned travel leg is rounded UP
    to the next 10 minutes (see round_up_travel) and shown as "20 min",
    "1 hr 10 min" -- never with seconds or false precision.
"""

import math

from services.i18n import gettext as _

import config

WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_hhmm(text):
    """'09:30' -> 570. Raises ValueError for anything that is not a valid HH:MM."""
    text = (text or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a time: {text!r}")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"not a time: {text!r}")
    return hours * 60 + minutes


def fmt_hhmm(minutes):
    """570 -> '09:30'. Rounds to the nearest minute."""
    minutes = int(round(minutes))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_duration(minutes):
    """95 -> '1 hr 35 min', 45 -> '45 min', 120 -> '2 hr', 0 -> '0 min'."""
    if minutes is None or minutes == math.inf:
        return "—"
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return _("{h} hr {m} min", h=hours, m=rest)
    if hours:
        return _("{h} hr", h=hours)
    return _("{m} min", m=rest)


def round_up_travel(minutes, step=None):
    """Conservative planning rule for travel estimates: round UP to the next `step` minutes.

        0 -> 0 (already there)     1..10 -> 10     11..20 -> 20     inf -> inf (no route)

    Rounding up (never down) means a schedule can only over-estimate travel, so
    a plan that fits on paper does not fail because a ride took 14 instead of 10 minutes.
    The rule is applied to the whole shortest path, not to each road link, so
    composing links does not inflate the estimate.
    """
    step = step or config.TRAVEL_ROUNDING_MIN
    if minutes == math.inf:
        return math.inf
    if minutes <= 0:
        return 0
    return int(step * math.ceil(minutes / step - 1e-9))


def fmt_travel(minutes):
    """A planned travel duration for display: '20 min', '1 hr 10 min', 'no route', 'no travel'."""
    if minutes == math.inf or minutes is None:
        return _("no route")
    if minutes == 0:
        return _("no travel")
    return fmt_duration(minutes)


def describe_days(weekdays):
    """[0..6] -> 'Daily'; [1..6] -> 'Tue-Sun'; otherwise a comma list."""
    days = sorted(set(weekdays))
    if len(days) == 7:
        return "Daily"
    if not days:
        return "Closed"
    # Find one run of consecutive days, allowing it to wrap past Sunday.
    for start in range(7):
        run = [(start + i) % 7 for i in range(len(days))]
        if sorted(run) == days:
            if len(days) == 1:
                return WEEKDAY_SHORT[start]
            return f"{WEEKDAY_SHORT[run[0]]}-{WEEKDAY_SHORT[run[-1]]}"
    return ", ".join(WEEKDAY_SHORT[d] for d in days)


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def fmt_short_date(d):
    """'Mon 2 Nov' in the interface language (the date itself is never parsed from this text)."""
    return f"{_(WEEKDAY_SHORT[d.weekday()])} {d.day} {_(MONTHS[d.month - 1][:3])}"


def fmt_long_date(d):
    """'Monday, 2 November 2026' in the interface language."""
    return f"{_(WEEKDAY_LONG[d.weekday()])}, {d.day} {_(MONTHS[d.month - 1])} {d.year}"
