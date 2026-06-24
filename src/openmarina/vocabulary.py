"""Controlled variable vocabulary -- the single source of truth for variable names.

Implements MASTER_INDEX Part 2 (v0.1). Every variable maps to its SI unit, a physical
sanity bound, a human meaning, and (for direction variables) the from/to convention.
Adapters import names from here and NEVER invent them; the conformance harness enforces it.

Principle: SI units, snake_case, source-agnostic names. Directions are degrees 0-360,
clockwise from true north. Convention split:
    wind/wave direction = "from"   (where it comes FROM)
    current direction   = "to"     (where it flows TO)
"""

from __future__ import annotations

from dataclasses import dataclass

from openmarina.types import VocabularyError

__all__ = ["Variable", "VOCAB", "VARIABLES", "get", "is_variable", "unit_for", "in_bounds"]


@dataclass(frozen=True)
class Variable:
    name: str
    unit: str                  # SI unit string (self-check column)
    lo: float | None           # inclusive sanity lower bound (None = unbounded)
    hi: float | None           # inclusive sanity upper bound (None = unbounded)
    meaning: str
    direction: str | None = None  # 'from' | 'to' for direction vars, else None


def _v(*args, **kw) -> tuple[str, Variable]:
    var = Variable(*args, **kw)
    return var.name, var


# --- the v0.1 controlled vocabulary (MASTER_INDEX 2.2) --------------------- #
VOCAB: dict[str, Variable] = dict([
    # Waves
    _v("wave_height_significant", "m",   0.0, 30.0, "significant wave height (Hs)"),
    _v("wave_period_dominant",    "s",   0.0, 30.0, "dominant/peak wave period (Tp)"),
    _v("wave_period_average",     "s",   0.0, 30.0, "average wave period"),
    _v("wave_direction",          "deg", 0.0, 360.0, "direction waves come FROM", direction="from"),
    _v("wave_height_max",         "m",   0.0, 40.0, "maximum individual wave height"),
    # Wind
    _v("wind_speed",              "m/s", 0.0, 120.0, "sustained wind speed"),
    _v("wind_gust",               "m/s", 0.0, 150.0, "gust speed"),
    _v("wind_direction",          "deg", 0.0, 360.0, "direction wind comes FROM", direction="from"),
    # Water / ocean
    _v("water_temperature",       "degree_celsius", -5.0, 40.0, "sea surface temperature"),
    _v("water_level",             "m",   -20.0, 20.0, "water level relative to stated datum"),
    _v("current_speed",           "m/s", 0.0, 15.0, "surface current speed"),
    _v("current_direction",       "deg", 0.0, 360.0, "direction current flows TO", direction="to"),
    _v("salinity",                "g/kg", 0.0, 50.0, "practical salinity"),
    # Atmosphere
    _v("air_temperature",         "degree_celsius", -60.0, 60.0, "air temperature"),
    _v("air_pressure",            "Pa",  80000.0, 110000.0, "barometric pressure (SI: Pa)"),
    _v("dewpoint_temperature",    "degree_celsius", -90.0, 60.0, "dewpoint"),
    _v("visibility",              "m",   0.0, 100000.0, "horizontal visibility"),
])

#: the set of valid variable names
VARIABLES: frozenset[str] = frozenset(VOCAB)


def is_variable(name: str) -> bool:
    return name in VOCAB


def get(name: str) -> Variable:
    """Return the Variable spec, or raise VocabularyError if the name is not in the vocab."""
    try:
        return VOCAB[name]
    except KeyError:
        raise VocabularyError(f"{name!r} is not in the controlled vocabulary") from None


def unit_for(name: str) -> str:
    return get(name).unit


def in_bounds(name: str, value: float) -> bool:
    """True if value is within the variable's physical sanity bounds (None bound = open)."""
    v = get(name)
    if value is None:
        return False
    if v.lo is not None and value < v.lo:
        return False
    if v.hi is not None and value > v.hi:
        return False
    return True
