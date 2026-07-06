"""NDBC adapter (adapter #1) -- NOAA National Data Buoy Center.

Parses the NDBC "realtime2" standard meteorological text file (whitespace-delimited,
~45 days of recent observations) into a CanonicalFrame using the controlled vocabulary.
Units are converted to SI; timestamps are UTC; missing values ('MM') are dropped.

Network I/O lives only in fetch()/list_stations(); the parser (_parse_met) is pure and
fixture-tested, so the risky part is verifiable without hitting the live agency.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pandas as pd

from openmarina.types import (
    AdapterFetchError,
    AdapterParseError,
    Capabilities,
    CanonicalFrame,
    Station,
)
from openmarina import vocabulary as vocab

REALTIME_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"
ACTIVE_STATIONS_URL = "https://www.ndbc.noaa.gov/activestations.xml"

# NDBC column -> (canonical variable, converter to SI)
_MET_MAP: dict[str, tuple[str, "callable"]] = {
    "WDIR": ("wind_direction", lambda x: x),                 # degT
    "WSPD": ("wind_speed", lambda x: x),                     # m/s
    "GST":  ("wind_gust", lambda x: x),                      # m/s
    "WVHT": ("wave_height_significant", lambda x: x),        # m
    "DPD":  ("wave_period_dominant", lambda x: x),           # s
    "APD":  ("wave_period_average", lambda x: x),            # s
    "MWD":  ("wave_direction", lambda x: x),                 # degT
    "PRES": ("air_pressure", lambda x: x * 100.0),          # hPa -> Pa
    "ATMP": ("air_temperature", lambda x: x),                # degC
    "WTMP": ("water_temperature", lambda x: x),              # degC
    "DEWP": ("dewpoint_temperature", lambda x: x),           # degC
    "VIS":  ("visibility", lambda x: x * 1852.0),           # nmi -> m
    "TIDE": ("water_level", lambda x: x * 0.3048),          # ft -> m (datum: MLLW)
}

_VARIABLES = tuple(v for v, _ in _MET_MAP.values())
_TIME_COLS = ["YY", "MM", "DD", "hh", "mm"]


class NdbcAdapter:
    """SourceAdapter for NOAA NDBC. No auth; ~45-day realtime window per station."""

    source_id = "ndbc"

    def __init__(self, session=None, timeout: float = 30.0):
        self._session = session   # inject a requests.Session in real use; lazy import otherwise
        self._timeout = timeout
        self._coords: dict[str, tuple[float, float]] = {}  # station_id -> (lat, lon) cache

    # -- contract ----------------------------------------------------------- #
    def capabilities(self) -> Capabilities:
        return Capabilities(
            source_id=self.source_id,
            variables=_VARIABLES,
            max_range_days=45.0,       # realtime2 window; historical archive is a later add
            update_cadence_s=1800.0,   # ~30 min typical
            requires_auth=False,
        )

    def list_stations(self) -> list[Station]:
        """Fetch the active-station list (lat/lon). Network; raises AdapterFetchError on failure."""
        text = self._http_get(ACTIVE_STATIONS_URL)
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(text)
            out: list[Station] = []
            for s in root.findall(".//station"):
                sid = s.get("id")
                lat, lon = s.get("lat"), s.get("lon")
                if not (sid and lat and lon):
                    continue
                station_id = f"ndbc:{sid.lower()}"
                self._coords[station_id] = (float(lat), float(lon))
                # aspirational: activestations.xml gives no per-variable truth; nearest(requires=...) probes
                out.append(Station(station_id, float(lat), float(lon), s.get("name"), _VARIABLES))
            return out
        except ET.ParseError as e:
            raise AdapterParseError(f"could not parse NDBC active-station list: {e}") from e

    def fetch(self, station_id, start=None, end=None, variables=None) -> CanonicalFrame:
        bare = station_id.split(":", 1)[-1].lower()
        lat, lon = self._station_coords(station_id)
        text = self._http_get(REALTIME_URL.format(station=bare.upper()))
        cf = self._parse_met(text, f"ndbc:{bare}", lat, lon, variables=variables)
        if start is not None or end is not None:
            cf = _time_filter(cf, start, end)
        return cf

    # -- pure parser (fixture-tested, no network) --------------------------- #
    @staticmethod
    def _parse_met(text, station_id, lat, lon, variables=None) -> CanonicalFrame:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        header_lines = [ln for ln in lines if ln.startswith("#")]
        if not header_lines:
            raise AdapterParseError("NDBC met file: no header line found")
        cols = header_lines[0].lstrip("#").split()
        data_lines = [ln for ln in lines if not ln.startswith("#")]
        if not data_lines:
            return CanonicalFrame.empty(meta=_provenance(station_id))
        try:
            df = pd.read_csv(
                io.StringIO("\n".join(data_lines)),
                sep=r"\s+", names=cols, na_values=["MM"], engine="python",
            )
            ts = pd.to_datetime(
                {"year": df["YY"], "month": df["MM"], "day": df["DD"],
                 "hour": df["hh"], "minute": df["mm"]},
                utc=True,
            )
        except (ValueError, KeyError) as e:
            raise AdapterParseError(f"NDBC met file: unexpected schema ({e})") from e

        wanted = set(variables) if variables else None
        records = []
        has_water_level = False
        for ndbc_col, (var, conv) in _MET_MAP.items():
            if ndbc_col not in df.columns:
                continue
            if wanted is not None and var not in wanted:
                continue
            unit = vocab.unit_for(var)
            series = pd.to_numeric(df[ndbc_col], errors="coerce")
            for t, raw in zip(ts, series):
                if pd.isna(raw):
                    continue  # missing ('MM') -> not emitted
                value = float(conv(float(raw)))
                qc = "good" if vocab.in_bounds(var, value) else "suspect"
                if var == "water_level":
                    has_water_level = True
                records.append((t, "ndbc", station_id, lat, lon, var, value, unit, qc))

        data = pd.DataFrame(records, columns=list(CanonicalFrame.COLUMNS))
        if not data.empty:
            data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
            data = data.sort_values(["variable", "timestamp"]).reset_index(drop=True)
        meta = _provenance(station_id)
        if has_water_level:
            meta["datum"] = "MLLW"   # NDBC tide is referenced to Mean Lower Low Water
        return CanonicalFrame(data=data, meta=meta)

    # -- helpers ------------------------------------------------------------ #
    def _station_coords(self, station_id):
        key = f"ndbc:{station_id.split(':', 1)[-1].lower()}"
        if key not in self._coords:
            self.list_stations()  # populates the cache
        if key not in self._coords:
            raise AdapterFetchError(f"unknown NDBC station: {station_id}")
        return self._coords[key]

    def _http_get(self, url: str) -> str:
        try:
            if self._session is not None:
                r = self._session.get(url, timeout=self._timeout)
            else:
                import requests
                r = requests.get(url, timeout=self._timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001 -- network failures are retryable
            raise AdapterFetchError(f"NDBC request failed for {url}: {e}") from e


def _provenance(station_id: str) -> dict:
    return {
        "provenance": {
            "agency": "NOAA NDBC",
            "endpoint": REALTIME_URL,
            "station": station_id,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
        "update_cadence_s": 1800.0,
    }


def _time_filter(cf: CanonicalFrame, start, end) -> CanonicalFrame:
    if cf.data.empty:
        return cf
    df = cf.data
    if start is not None:
        df = df[df["timestamp"] >= pd.to_datetime(start, utc=True)]
    if end is not None:
        df = df[df["timestamp"] <= pd.to_datetime(end, utc=True)]
    return CanonicalFrame(df.reset_index(drop=True), dict(cf.meta))
