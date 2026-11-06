"""Cronometraje sin instrumentación de memoria dentro del intervalo."""

import time


def timed(action):
    started = time.perf_counter_ns()
    result = action()
    return (time.perf_counter_ns() - started) / 1e9, result
