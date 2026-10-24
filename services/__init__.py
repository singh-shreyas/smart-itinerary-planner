"""Business logic between the Flask routes and the pure algorithms.

    models.py               dataclasses (Attraction, TripRequest, Visit, DayPlan, Itinerary, ...)
    timeutil.py             'HH:MM' <-> minutes, weekday names
    trip_request.py         server-side validation of trip parameters
    city_data.py            load a city from SQLite, build the graph, run Dijkstra (cached)
    scheduler.py            simulate one day's timeline (opening hours, travel, return by day end)
    itinerary_generator.py  the day-by-day planning pipeline
    validator.py            independent re-check of every constraint in a finished itinerary
    comparison.py           runs every strategy on identical input and measures them
    crosscheck.py           NetworkX cross-check of our Dijkstra
    timing.py               median-of-N timing helper
    algorithm_info.py       algorithm descriptions shown on the home and About pages
"""
