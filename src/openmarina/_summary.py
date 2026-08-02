"""summary() -- one call, the marine picture around a point.

The capability groups a mariner actually asks about (waves, wind, tide, temperature)
rarely live on one station: the wave buoy is offshore, the tide gauge is in the harbor.
summary() runs the nearest-capable probe (see core.nearest) once per group -- each group
independently -- and returns the freshest good observation per variable, station-attributed.

    import openmarina
    s = openmarina.summary(25.77, -80.13)          # Miami Beach
    s = openmarina.summary_zip("33139")
    s.groups["wave"].values["wave_height_significant"]   # meters, SI
    s.to_dict()                                          # JSON-ready

Partial success is normal and honest: a group with no capable station within the probe
budget comes back as None (the ocean has no tide gauge; the harbor has no wave buoy).
Only when every group fails does summary() raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from openmarina import vocabulary as vocab
from openmarina.core import _adapter_for, _haversine_km
from openmarina.geocode import zip_to_latlon
from openmarina.types import AdapterFetchError, AdapterParseError

__all__ = ["GroupReading", "Summary", "GROUPS", "summary", "summary_zip"]


# Capability groups: source to ask, variables that make a station qualify (required),
# and variables harvested opportunistically from the same frame (optional).
GROUPS: dict[str, dict] = {
    "wave": {
        "source": "ndbc",
        "required": ("wave_height_significant",),
        "optional": ("wave_period_dominant", "wave_period_average",
                     "wave_direction", "wave_height_max"),
    },
    "wind": {
        "source": "ndbc",
        "required": ("wind_speed", "wind_direction"),
        "optional": ("wind_gust",),
    },
    "tide": {
        "source": "coops",
        "required": ("water_level",),
        "optional": (),
    },
    "temp": {
        "source": "ndbc",
        "required": ("water_temperature",),
        "optional": ("air_temperature", "air_pressure"),
    },
}


@dataclass(frozen=True)
class GroupReading:
    """The freshest good observations for one capability group, from one station."""

    group: str
    station_id: str                     # canonical 'source:station'
    station_name: str | None
    lat: float
    lon: float
    distance_km: float
    time: datetime                      # newest observation timestamp used
    values: dict[str, float] = field(default_factory=dict)   # variable -> SI value
    units: dict[str, str] = field(default_factory=dict)      # variable -> SI unit

    def to_dict(self) -> dict:
        return {
            "station_id": self.station_id,
            "station_name": self.station_name,
            "lat": self.lat,
            "lon": self.lon,
            "distance_km": round(self.distance_km, 1),
            "time": self.time.isoformat(),
            "values": dict(self.values),
            "units": dict(self.units),
        }


@dataclass(frozen=True)
class Summary:
    """summary()'s return: per-group readings around a point. None = no capable station."""

    lat: float
    lon: float
    groups: dict[str, GroupReading | None]

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "groups": {g: (r.to_dict() if r else None) for g, r in self.groups.items()},
        }


def _latest_good(cf, wanted: tuple[str, ...]) -> tuple[dict, dict, datetime | None]:
    """From a long CanonicalFrame, the newest qc_flag=='good' value per wanted variable."""
    values: dict[str, float] = {}
    units: dict[str, str] = {}
    newest: datetime | None = None
    if cf.data.empty:
        return values, units, newest
    good = cf.data[cf.data["qc_flag"] == "good"]
    for name in wanted:
        rows = good[good["variable"] == name]
        if rows.empty:
            continue
        row = rows.loc[rows["timestamp"].idxmax()]
        values[name] = float(row["value"])
        units[name] = str(row["unit"])
        t = row["timestamp"].to_pydatetime()
        newest = t if newest is None or t > newest else newest
    return values, units, newest


def _probe_group(group: str, spec: dict, lat: float, lon: float,
                 max_probes: int, probe_window_h: float) -> GroupReading | None:
    """core.nearest()'s probe loop, kept inline so the qualifying fetch is reused for the
    reading itself (probing then re-fetching would double the network cost per group)."""
    required = set(spec["required"])
    wanted = tuple(spec["required"]) + tuple(spec["optional"])
    try:
        adapter = _adapter_for(spec["source"])
        stations = adapter.list_stations()
    except (AdapterFetchError, AdapterParseError, ValueError):
        return None
    stations = sorted(stations, key=lambda s: _haversine_km(lat, lon, s.lat, s.lon))
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=probe_window_h)
    for st in stations[:max_probes]:
        try:
            cf = adapter.fetch(st.station_id, start=start, end=end, variables=list(wanted))
        except (AdapterFetchError, AdapterParseError):
            continue
        values, units, newest = _latest_good(cf, wanted)
        if required <= set(values):
            return GroupReading(
                group=group,
                station_id=st.station_id,
                station_name=st.name,
                lat=st.lat,
                lon=st.lon,
                distance_km=_haversine_km(lat, lon, st.lat, st.lon),
                time=newest,
                values=values,
                units=units,
            )
    return None


def summary(lat: float, lon: float, groups=None,
            max_probes: int = 8, probe_window_h: float = 6.0) -> Summary:
    """The marine picture around (lat, lon): nearest capable station per group.

    `groups` limits which capability groups run (default: all of GROUPS). Each group
    probes independently -- see GROUPS for what qualifies a station. A group with no
    capable station within `max_probes` candidates is None in the result; if every
    requested group is None, raises AdapterFetchError.
    """
    names = tuple(groups) if groups else tuple(GROUPS)
    bad = [g for g in names if g not in GROUPS]
    if bad:
        raise ValueError(f"unknown group(s): {bad}; known groups: {sorted(GROUPS)}")
    for g in names:
        for var in (*GROUPS[g]["required"], *GROUPS[g]["optional"]):
            assert vocab.is_variable(var), f"GROUPS[{g!r}] names unknown variable {var!r}"

    readings = {
        g: _probe_group(g, GROUPS[g], lat, lon, max_probes, probe_window_h)
        for g in names
    }
    if all(r is None for r in readings.values()):
        raise AdapterFetchError(
            f"no capable station found for any requested group {sorted(names)} "
            f"near ({lat}, {lon}) within {max_probes} candidates per group"
        )
    return Summary(lat=lat, lon=lon, groups=readings)


def summary_zip(zipcode: str, country: str = "us", groups=None,
                max_probes: int = 8, probe_window_h: float = 6.0) -> Summary:
    """Like summary(), from a ZIP/postal code. Needs the optional 'pgeocode' package."""
    lat, lon = zip_to_latlon(zipcode, country=country)
    return summary(lat, lon, groups=groups,
                   max_probes=max_probes, probe_window_h=probe_window_h)
