"""SignalK delta output -- feed openmarina data to a SignalK consumer.

Converts CanonicalFrames or a Summary into SignalK delta messages so shore/buoy
observations can be injected into a SignalK stream (e.g. a display that already
speaks SignalK). Unit conversions follow the SignalK spec's SI conventions:
angles in radians, temperatures in Kelvin -- speeds (m/s), pressure (Pa) and
lengths (m) are already SI in the controlled vocabulary and pass through.

Path notes (honesty over pretence):
  - Wind maps to environment.wind.speedTrue/directionTrue -- it is TRUE wind at the
    reporting station, never the vessel's apparent wind. The delta's source block
    carries the station id and "openmarina" label so a consumer can tell remote
    observation from onboard sensor.
  - Wave/level paths (environment.wave.*, environment.water.level) are the closest
    conventional homes; SignalK 1.x has no single blessed path for every marine
    observable. The mapping table below is the single edit point.
"""

from __future__ import annotations

import math
from datetime import datetime

from openmarina.types import CanonicalFrame

__all__ = ["SIGNALK_PATHS", "frame_to_deltas", "summary_to_deltas"]


#: controlled-vocabulary variable -> SignalK path (single edit point)
SIGNALK_PATHS: dict[str, str] = {
    "wave_height_significant": "environment.wave.significantHeight",
    "wave_period_dominant":    "environment.wave.period",
    "wave_period_average":     "environment.wave.periodAverage",
    "wave_direction":          "environment.wave.direction",
    "wave_height_max":         "environment.wave.maxHeight",
    "wind_speed":              "environment.wind.speedTrue",
    "wind_gust":               "environment.wind.gust",
    "wind_direction":          "environment.wind.directionTrue",
    "water_temperature":       "environment.water.temperature",
    "water_level":             "environment.water.level",
    "current_speed":           "environment.current.drift",
    "current_direction":       "environment.current.setTrue",
    "salinity":                "environment.water.salinity",
    "air_temperature":         "environment.outside.temperature",
    "air_pressure":            "environment.outside.pressure",
    "dewpoint_temperature":    "environment.outside.dewPointTemperature",
    "visibility":              "environment.outside.horizontalVisibility",
}

_DEG_TO_RAD = ("wave_direction", "wind_direction", "current_direction")
_C_TO_K = ("water_temperature", "air_temperature", "dewpoint_temperature")


def _si_to_signalk(variable: str, value: float) -> float:
    if variable in _DEG_TO_RAD:
        return math.radians(value)
    if variable in _C_TO_K:
        return value + 273.15
    return value


def _delta(station_id: str, timestamp: datetime, values: list[dict], context: str) -> dict:
    return {
        "context": context,
        "updates": [
            {
                "source": {"label": "openmarina", "src": station_id},
                "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "values": values,
            }
        ],
    }


def frame_to_deltas(cf: CanonicalFrame, context: str = "vessels.self") -> list[dict]:
    """One delta per (station, timestamp), qc_flag=='good' rows only, mapped variables only.

    Deltas come back oldest-first so replaying them into a consumer preserves time order.
    """
    deltas: list[dict] = []
    if cf.data.empty:
        return deltas
    good = cf.data[cf.data["qc_flag"] == "good"]
    good = good[good["variable"].isin(SIGNALK_PATHS)]
    if good.empty:
        return deltas
    for (station_id, ts), rows in sorted(
        good.groupby(["station_id", "timestamp"]), key=lambda kv: kv[0][1]
    ):
        values = [
            {
                "path": SIGNALK_PATHS[r["variable"]],
                "value": _si_to_signalk(r["variable"], float(r["value"])),
            }
            for _, r in rows.iterrows()
        ]
        deltas.append(_delta(str(station_id), ts.to_pydatetime(), values, context))
    return deltas


def summary_to_deltas(s, context: str = "vessels.self") -> list[dict]:
    """One delta per non-None group in a Summary (each group = one station snapshot)."""
    deltas: list[dict] = []
    for reading in s.groups.values():
        if reading is None:
            continue
        values = [
            {
                "path": SIGNALK_PATHS[name],
                "value": _si_to_signalk(name, value),
            }
            for name, value in reading.values.items()
            if name in SIGNALK_PATHS
        ]
        if values:
            deltas.append(_delta(reading.station_id, reading.time, values, context))
    return deltas
