"""Pit under this caution? An estimate from past stops made at the same point of a caution.

Learned from earlier races (see :func:`stintwise.fit.fit_caution_model`): for every
measured stop under FCY or Safety Car, how long the caution had been out when the car
came in and what share of its pit-lane time it saved against the cars that stayed out.
That share already includes the chance that the caution ended during the stop.

For a decision now, the ``K`` past stops made closest to the same elapsed caution time
give: the chance the stop gains time (more than ``THRESHOLD_S``), the median gain and
a p10-p90 range, all scaled to our planned pit-lane time.
"""
from __future__ import annotations

K = 25
THRESHOLD_S = 5.0


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def distance(a: float, b: float) -> float:
    """Relative distance between two elapsed caution times (a minute apart matters
    more early in a caution than late). Plain arithmetic, so the Python and
    JavaScript engines rank neighbours identically."""
    a, b = max(0.0, a), max(0.0, b)
    return abs(a - b) / (min(a, b) + 60.0)


def neighbours(entry: dict, elapsed: float, k: int = K) -> list[list[float]]:
    rows = entry.get("samples") or []
    ranked = sorted(rows, key=lambda r: (distance(r[0], elapsed), r[0], r[1]))
    return ranked[:k]


def assess(entry: dict, elapsed: float, pit_time: float) -> dict | None:
    """Chance of gaining time, median gain and range (seconds) for a stop starting now."""
    near = neighbours(entry, elapsed)
    if len(near) < 5:
        return None
    gains = [r[1] * pit_time for r in near]
    mid = _quantile(gains, 0.5)
    q = entry.get("residual_q90", entry.get("residual_q80"))
    if q is not None:  # conformal: 90% of outcomes on unseen earlier races fell inside
        rng = (mid - q * pit_time, mid + q * pit_time)
    else:
        rng = (_quantile(gains, 0.1), _quantile(gains, 0.9))
    return {
        "p_gain": sum(1 for g in gains if g > THRESHOLD_S) / len(gains),
        "gain_s": mid,
        "range_s": rng,  # holds ~90% of outcomes on races the model had not seen
        "middle_s": (_quantile(gains, 0.25), _quantile(gains, 0.75)),  # middle half
        "n": len(near),
    }
