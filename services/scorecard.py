"""Score and recommend selection strategies from their ACTUAL plans (comparison page).

Raw metrics (per strategy, whole trip):
    stops            number of places visited                        (coverage)
    value            sum of the places' value scores                 (quality)
    avg_value        value / stops
    travel_min       planned travel minutes (local + intercity + meal detours)
    travel_per_stop  travel_min / stops                              (travel efficiency)
    utilisation      sightseeing minutes / available minutes         (time utilisation)
    violations       problems found by the independent validator     (feasibility)
    runtime_ms       planning time -- reported, never scored

Subscores: each metric is normalised against the best strategy ON THIS TRIP,
so 100 means "best of the three" and quantities in different units (minutes,
counts, shares) are never added together directly:
    higher is better:  sub = 100 * value / best value
    lower is better:   sub = 100 * best value / value
A strategy with no stops scores 0 on every subscore.

Overall = sum(weight * subscore) with config.SCORECARD_WEIGHTS:
    value 0.45 + coverage 0.20 + travel 0.20 + utilisation 0.15 = 1.00
There is no money component: the planner does not optimise cost, so the score
does not pretend to measure it.

Feasibility is a GATE, not a subscore: a plan with any validator violation is
marked infeasible and is never recommended, however many stops it has.
If the best feasible plans tie (same overall to 0.1, or identical timelines),
the page says so instead of inventing a winner.
"""

import config
from services.i18n import gettext as _, ngettext

METRIC_DIRECTIONS = {        # subscore name -> (raw metric, "max" or "min")
    "value": ("value", "max"),
    "coverage": ("stops", "max"),
    "travel": ("travel_per_stop", "min"),
    "utilisation": ("utilisation", "max"),
}

LABELS = {"value": "Value", "coverage": "Coverage", "travel": "Travel efficiency",
          "utilisation": "Time utilisation"}


def raw_metrics(itinerary):
    stops = itinerary.stops
    value = itinerary.score
    travel = itinerary.travel_min
    available = itinerary.available_min
    return {
        "stops": stops,
        "value": value,
        "avg_value": round(value / stops, 1) if stops else 0.0,
        "travel_min": travel,
        "intercity_min": itinerary.intercity_min,
        "travel_per_stop": round(travel / stops, 1) if stops else None,
        "sight_min": itinerary.sight_min,
        "meal_min": itinerary.meal_min,
        "wait_min": itinerary.wait_min,
        "buffer_min": itinerary.buffer_min,
        "free_min": itinerary.free_min,
        "available_min": available,
        "utilisation": round(itinerary.sight_min / available, 4) if available else 0.0,
        "km": itinerary.km,
        "violations": len(itinerary.violations),
        "empty_days": sum(1 for d in itinerary.days if not d.visits),
    }


def _subscore(value, best, direction):
    if value is None or best is None:
        return 0.0
    if direction == "max":
        return 100.0 if best == 0 else round(100 * value / best, 1)
    return 100.0 if value == 0 else round(100 * best / value, 1)


def subscores(rows):
    """rows: [{key, metrics}] -> adds 'subscores' and 'overall' to each row. Returns the weights used."""
    weights = dict(config.SCORECARD_WEIGHTS)

    for name, (metric, direction) in METRIC_DIRECTIONS.items():
        values = [row["metrics"][metric] if row["metrics"]["stops"] else None for row in rows]
        present = [v for v in values if v is not None]
        best = (max(present) if direction == "max" else min(present)) if present else None
        for row, v in zip(rows, values):
            row.setdefault("subscores", {})[name] = _subscore(v, best, direction)
    for row in rows:
        row["overall"] = round(sum(weights.get(k, 0) * s for k, s in row["subscores"].items()), 1)
        row["feasible"] = row["metrics"]["violations"] == 0
    return weights


def recommend(rows, signatures):
    """Pick the recommended strategy among FEASIBLE plans, honest about ties.

    signatures: {key: plan fingerprint} -- identical timelines are reported as identical.
    Returns {"status": "winner" | "tie" | "none", "keys": [...], "identical": [[k1, k2], ...], "text": str}
    """
    identical = []
    keys = [r["key"] for r in rows]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if signatures.get(a) and signatures.get(a) == signatures.get(b):
                identical.append([a, b])

    feasible = [r for r in rows if r["feasible"] and r["metrics"]["stops"] > 0]
    if not feasible:
        return {"status": "none", "keys": [], "identical": identical,
                "text": _("No strategy produced a feasible plan with at least one stop, so nothing is recommended.")}
    top = max(r["overall"] for r in feasible)
    leaders = [r for r in feasible if abs(r["overall"] - top) < 0.05]
    names = [_(config.STRATEGY_SHORT[r["key"]]) for r in leaders]
    if len(leaders) > 1:
        same = all([a["key"], b["key"]] in identical or [b["key"], a["key"]] in identical
                   for i, a in enumerate(leaders) for b in leaders[i + 1:])
        joined = _(" and ").join(names)
        text = (_("{names} produced the same itinerary (overall {score}). There is no single winner on this trip.",
                  names=joined, score=f"{top:.1f}") if same else
                _("{names} produced equally good plans (overall {score}). There is no single winner on this trip.",
                  names=joined, score=f"{top:.1f}"))
        return {"status": "tie", "keys": [r["key"] for r in leaders], "identical": identical, "text": text}
    winner = leaders[0]
    runner = max((r for r in feasible if r is not winner), key=lambda r: r["overall"], default=None)
    if runner:
        text = _("{name} has the best overall score on this trip ({score}, {margin} points ahead of {runner}).",
                 name=names[0], score=f"{top:.1f}", margin=f"{top - runner['overall']:.1f}",
                 runner=_(config.STRATEGY_SHORT[runner["key"]]))
    else:
        text = _("{name} has the best overall score on this trip ({score}).", name=names[0], score=f"{top:.1f}")
    return {"status": "winner", "keys": [winner["key"]], "identical": identical, "text": text}


def tradeoffs(rows):
    """Plain-language comparisons of the raw metrics (only differences that exist are mentioned)."""
    notes = []
    by_key = {r["key"]: r["metrics"] for r in rows}
    short = {k: _(v) for k, v in config.STRATEGY_SHORT.items()}

    def compare(a, b):
        ma, mb = by_key[a], by_key[b]
        parts = []
        if ma["stops"] != mb["stops"]:
            more, fewer = (a, b) if ma["stops"] > mb["stops"] else (b, a)
            parts.append(ngettext("{a} fits {n} more stop than {b}", "{a} fits {n} more stops than {b}",
                                  abs(ma["stops"] - mb["stops"]), a=short[more], b=short[fewer]))
        if ma["value"] != mb["value"]:
            hi, lo = (a, b) if ma["value"] > mb["value"] else (b, a)
            parts.append(_("{a} collects {n} more value points", a=short[hi], n=abs(ma["value"] - mb["value"])))
        if ma["avg_value"] != mb["avg_value"] and ma["stops"] and mb["stops"]:
            hi = a if ma["avg_value"] > mb["avg_value"] else b
            parts.append(_("{a}'s places are better on average ({high} vs {low})", a=short[hi],
                           high=max(ma["avg_value"], mb["avg_value"]), low=min(ma["avg_value"], mb["avg_value"])))
        if ma["travel_min"] != mb["travel_min"]:
            less = a if ma["travel_min"] < mb["travel_min"] else b
            parts.append(_("{a} travels {n} min less", a=short[less], n=abs(ma["travel_min"] - mb["travel_min"])))
        return parts

    keys = [r["key"] for r in rows]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            parts = compare(a, b)
            if parts:
                notes.append(_("{a} vs {b}: {parts}.", a=short[a], b=short[b], parts="; ".join(parts)))
            else:
                notes.append(_("{a} and {b} have identical metrics on this trip.", a=short[a], b=short[b]))
    return notes
