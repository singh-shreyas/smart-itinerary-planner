"""Timing helper for the comparison page and the benchmark script.

One untimed warm-up run, then the MEDIAN of `repeats` timed runs. A single run
of a function that takes microseconds is dominated by timer noise, so we never
report one.
"""

import time


def median_ms(function, repeats=5):
    function()
    samples = []
    for _ in range(max(1, repeats)):
        started = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - started) / 1e6)
    samples.sort()
    return samples[len(samples) // 2]
