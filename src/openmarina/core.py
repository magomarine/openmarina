"""Core convenience: load() / nearest().

The one-line surface so `import openmarina` pulls a clean frame. Adapters stay dumb
(3 methods); the core owns the registry and (later) caching/retry/merge.
"""

from __future__ import annotations

import math

import pandas as pd
from datetime import datetime, timedelta, timezone

from openmarina.types import CanonicalFrame, Station
from openmarina.adapters.ndbc import NdbcAdapter
from openmarina.adapters.coops import CoopsAdapter
from openmarina.geocode import zip_to_latlon

# Source registry. Adding an agency = register its adapter here (and ship the adapter).
_ADAPTERS = {
    "ndbc": NdbcAdapter,
    "coops": CoopsAdapter,
}


def _adapter_for(source: str):
    try:
        return _ADAPTERS[source]()
    except KeyError:
        raise ValueError(
            f"unknown source {source!r}; known sources: {sorted(_ADAPTERS)}"
        ) from None


def load(station_id, start=None, end=None, variables=None) -> CanonicalFrame:
    """Pull one station's data into a CanonicalFrame.

    station_id is 'source:station', e.g. 'ndbc:41122'. start/end accept datetimes or
    parseable strings; if omitted, defaults to the last 24 hours (the daily-pull case).
    Use the returned frame's .data (long) or .to_wide() (analysis) as you like.
    """
    if ":" not in station_id:
        raise ValueError("station_id must be 'source:station', e.g. 'ndbc:41122'")
    source = station_id.split(":", 1)[0].lower()
    if end is None:
        end = datetime.now(timezone.utc)
    if start is None:
        start = end - timedelta(days=1)
    return _adapter_for(source).fetch(station_id, start, end, variables)


def load_many(station_ids, start=None, end=None, variables=None) -> CanonicalFrame:
    """Load several stations and merge into one CanonicalFrame (long format).

    Long/tidy shape makes this trivial: just concatenate. `to_wide()` then keeps the
    stations apart (station_id is in the wide index). Great for "compare two buoys" or
    feeding multiple stations into one downstream consumer.
    """
    frames = [load(sid, start, end, variables) for sid in station_ids]
    if not frames:
        return CanonicalFrame.empty()
    data = pd.concat([f.data for f in frames], ignore_index=True)
    meta = {
        "provenance": [f.meta.get("provenance") for f in frames],
        "stations": list(station_ids),
    }
    return CanonicalFrame(data, meta)


def nearest(lat, lon, source="ndbc") -> Station:
    """Return the closest station from `source` to (lat, lon) (great-circle distance).

    Convenience for "what's the buoy near me." Requires the source's station list (network).
    """
    stations = _adapter_for(source).list_stations()
    if not stations:
        raise ValueError(f"no stations available from source {source!r}")
    return min(stations, key=lambda s: _haversine_km(lat, lon, s.lat, s.lon))


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_zip(zipcode, source="ndbc", country="us") -> Station:
    """Like nearest(), but you give a ZIP/postal code instead of lat/lon.

        nearest_zip("33139")   # Miami Beach -> closest station
    Needs the optional 'pgeocode' package (see openmarina.geocode).
    """
    lat, lon = zip_to_latlon(zipcode, country=country)
    return nearest(lat, lon, source)
