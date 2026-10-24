"""Time helpers. The planner works in integer minutes after midnight (09:30 -> 570)."""

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
    """95 -> '1 h 35 min', 45 -> '45 min', 120 -> '2 h'."""
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    if hours:
        return f"{hours} h"
    return f"{rest} min"


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
