"""ERDDAP adapter (adapter #3) — one adapter, many agencies.

ERDDAP is a standardized data server used by 60+ providers (US IOOS regionals, Ireland's
Marine Institute, Australia's AODN, …). Its `tabledap` protocol serves in-situ point/station
data through ONE uniform API. So a single *configurable* adapter — parameterized by server URL +
dataset id + a variable map — reaches all of them.

Because ERDDAP datasets use their own (often CF-standard) variable names and units, this adapter
maps them into openmarina's controlled vocabulary and converts units to SI. A sensible default
CF-name map is built in; pass `var_map` to override per dataset.

Not in the zero-arg `load()` registry (it needs config). Construct it directly:

    adp = ErddapAdapter("https://erddap.server", "my_dataset", source_id="neracoos",
                        station_col="station")
    cf = adp.fetch("neracoos:44098", start, end)

Parser (_parse_table) is pure and fixture-tested; only fetch()/list_stations() touch the network.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from openmarina import vocabulary as vocab
from openmarina.types import (
    AdapterFetchError,
    AdapterParseError,
    Capabilities,
    CanonicalFrame,
    Station,
)

# Default ERDDAP/CF standard-name -> controlled-vocabulary variable.
DEFAULT_VAR_MAP: dict[str, str] = {
    "sea_surface_wave_significant_height": "wave_height_significant",
    "significant_wave_height": "wave_height_significant",
    "sea_surface_wave_period_at_variance_spectral_density_maximum": "wave_period_dominant",
    "dominant_wave_period": "wave_period_dominant",
    "sea_surface_wave_mean_period": "wave_period_average",
    "average_wave_period": "wave_period_average",
    "sea_surface_wave_from_direction": "wave_direction",
    "mean_wave_direction": "wave_direction",
    "wind_speed": "wind_speed",
    "wind_from_direction": "wind_direction",
    "wind_speed_of_gust": "wind_gust",
    "sea_water_temperature": "water_temperature",
    "sea_surface_temperature": "water_temperature",
    "air_temperature": "air_temperature",
    "air_pressure": "air_pressure",
    "air_pressure_at_sea_level": "air_pressure",
    "sea_water_practical_salinity": "salinity",
    "sea_water_salinity": "salinity",
    "dew_point_temperature": "dewpoint_temperature",
    "visibility_in_air": "visibility",
}


class ErddapAdapter:
    """Configurable SourceAdapter over any ERDDAP tabledap dataset."""

    def __init__(self, server, dataset_id, *, source_id="erddap", var_map=None,
                 time_col="time", lat_col="latitude", lon_col="longitude",
                 station_col=None, default_datum=None, session=None, timeout: float = 60.0):
        self.source_id = source_id
        self._server = server.rstrip("/")
        self._dataset = dataset_id
        self._var_map = dict(var_map) if var_map else dict(DEFAULT_VAR_MAP)
        self._time_col, self._lat_col, self._lon_col = time_col, lat_col, lon_col
        self._station_col = station_col
        self._datum = default_datum
        self._session = session
        self._timeout = timeout

    # -- contract ----------------------------------------------------------- #
    def capabilities(self) -> Capabilities:
        return Capabilities(
            source_id=self.source_id,
            variables=tuple(sorted(set(self._var_map.values()))),
            max_range_days=None,
            update_cadence_s=None,
            requires_auth=False,   # most ERDDAP servers are open; per-dataset LICENSE varies
        )

    def list_stations(self) -> list[Station]:
        if not self._station_col:
            raise AdapterFetchError("station_col not configured for this ERDDAP dataset")
        cols = f"{self._station_col},{self._lat_col},{self._lon_col}"
        url = f"{self._server}/erddap/tabledap/{self._dataset}.json?{cols}&distinct()"
        obj = self._get_json(url)
        table = obj.get("table", {})
        names = table.get("columnNames", [])
        idx = {n: i for i, n in enumerate(names)}
        out = []
        for row in table.get("rows", []):
            sid = row[idx[self._station_col]]
            lat, lon = row[idx[self._lat_col]], row[idx[self._lon_col]]
            if sid is None or lat is None or lon is None:
                continue
            out.append(Station(f"{self.source_id}:{sid}", float(lat), float(lon), str(sid),
                               tuple(sorted(set(self._var_map.values())))))
        return out

    def fetch(self, station_id, start=None, end=None, variables=None) -> CanonicalFrame:
        if start is None or end is None:
            raise AdapterFetchError("ERDDAP fetch requires start and end")
        bare = station_id.split(":", 1)[-1]
        data_cols = [c for c, v in self._var_map.items()
                     if (variables is None or v in variables)]
        req_cols = [self._time_col, self._lat_col, self._lon_col]
        if self._station_col:
            req_cols.append(self._station_col)
        req_cols += data_cols
        q = ",".join(req_cols)
        s, e = _iso(start), _iso(end)
        url = f"{self._server}/erddap/tabledap/{self._dataset}.json?{q}&{self._time_col}>={s}&{self._time_col}<={e}"
        if self._station_col:
            url += f'&{self._station_col}="{bare}"'
        obj = self._get_json(url)
        return self._parse_table(obj, station_id, self._var_map, self._time_col,
                                 self._lat_col, self._lon_col, self._station_col,
                                 self.source_id, self._datum)

    # -- pure parser (fixture-tested) --------------------------------------- #
    @staticmethod
    def _parse_table(obj, station_id, var_map, time_col, lat_col, lon_col,
                     station_col, source_id, datum):
        table = obj.get("table") if isinstance(obj, dict) else None
        if not table:
            raise AdapterParseError("ERDDAP response missing 'table'")
        names = table.get("columnNames", [])
        units = table.get("columnUnits", [None] * len(names))
        idx = {n: i for i, n in enumerate(names)}
        for required in (time_col, lat_col, lon_col):
            if required not in idx:
                raise AdapterParseError(f"ERDDAP table missing column {required!r}")

        rows, has_wl = [], False
        for r in table.get("rows", []):
            try:
                ts = pd.to_datetime(r[idx[time_col]], utc=True)
                lat = float(r[idx[lat_col]]); lon = float(r[idx[lon_col]])
            except (KeyError, TypeError, ValueError):
                continue
            sid = f"{source_id}:{r[idx[station_col]]}" if station_col and station_col in idx else station_id
            for col, var in var_map.items():
                if col not in idx:
                    continue
                raw = r[idx[col]]
                if raw in ("", None):
                    continue
                try:
                    val0 = float(raw)
                except (TypeError, ValueError):
                    continue
                val, converted = _to_si(var, val0, units[idx[col]] if idx[col] < len(units) else None)
                if var == "water_level":
                    has_wl = True
                qc = ("good" if vocab.in_bounds(var, val) else "suspect") if converted else "unverified"
                rows.append((ts, source_id, sid, lat, lon, var, val, vocab.unit_for(var), qc))

        data = pd.DataFrame(rows, columns=list(CanonicalFrame.COLUMNS))
        if not data.empty:
            data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
            data = data.drop_duplicates(subset=["station_id", "variable", "timestamp"])
            data = data.sort_values(["station_id", "variable", "timestamp"]).reset_index(drop=True)
        meta = {"provenance": {"agency": f"ERDDAP:{source_id}", "station": station_id,
                               "retrieved_at": datetime.now(timezone.utc).isoformat()}}
        if has_wl and datum:
            meta["datum"] = datum
        return CanonicalFrame(data=data, meta=meta)

    def _get_json(self, url):
        try:
            if self._session is not None:
                r = self._session.get(url, timeout=self._timeout)
            else:
                import requests
                r = requests.get(url, timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            raise AdapterFetchError(f"ERDDAP request failed for {url}: {e}") from e


def _iso(dt) -> str:
    return pd.to_datetime(dt, utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(u):
    return (u or "").strip().lower().replace(" ", "").replace(".", "").replace("-", "")


def _to_si(var, value, unit_src):
    """Convert value to the variable's SI unit. Returns (value, converted_ok)."""
    target = vocab.unit_for(var)
    u = _norm(unit_src)
    if target == "degree_celsius":
        if u in ("k", "kelvin"):
            return value - 273.15, True
        if u in ("", "degc", "degreec", "degreecelsius", "celsius", "c", "degreescelsius"):
            return value, True
        return value, False
    if target == "Pa":
        if u in ("hpa", "mbar", "millibar", "millibars", "mb"):
            return value * 100.0, True
        if u in ("kpa",):
            return value * 1000.0, True
        if u in ("pa", "pascal", ""):
            return value, True
        return value, False
    if target == "m/s":
        if u in ("ms1", "m/s", "meters1", "meterssecond1", "mpers"):
            return value, True
        if u in ("knot", "knots", "kt", "kn"):
            return value * 0.514444, True
        if u in ("km/h", "kmh1", "kph"):
            return value / 3.6, True
        return value, (u == "")
    if target == "deg":
        if u in ("", "degree", "degrees", "degreestrue", "degree_true", "degt"):
            return value, True
        return value, False
    if target == "m":  # wave heights, water_level
        if u in ("", "m", "meter", "meters"):
            return value, True
        if u in ("cm", "centimeter", "centimeters"):
            return value / 100.0, True
        if u in ("ft", "feet", "foot"):
            return value * 0.3048, True
        return value, False
    if target == "s":
        if u in ("", "s", "sec", "second", "seconds"):
            return value, True
        return value, False
    if target == "g/kg":  # salinity (PSU ~ g/kg)
        if u in ("", "1", "psu", "1e3", "001", "gkg", "g/kg"):
            return value, True
        return value, False
    # default: pass through, unverified unit
    return value, (u == "")
