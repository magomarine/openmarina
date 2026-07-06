"""Core convenience: load() / nearest().

The one-line surface so `import openmarina` pulls a clean frame. Adapters stay dumb
(3 methods); the core owns the registry and (later) caching/retry/merge.
"""

from __future__ import annotations

import math

import pandas as pd
from datetime import datetime, timedelta, timezone

from openmarina.types import AdapterFetchError, AdapterParseError, CanonicalFrame, Station
from openmarina.adapters.ndbc import NdbcAdapter
from openmarina.adapters.coops import CoopsAdapter
from openmarina.geocode import zip_to_latlon
from openmarina import vocabulary as vocab

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


def nearest(lat, lon, source="ndbc", requires=None, max_probes=8, probe_window_h=6.0) -> Station:
    """Return the closest station from `source` to (lat, lon) (great-circle distance).

    Convenience for "what's the buoy near me." Requires the source's station list (network).

    Why probing exists: a source's station list (e.g. NDBC's activestations.xml) mixes station
    types -- wave buoys alongside tide gauges that report no wave columns -- and the variables
    a station lists are aspirational, not verified (the list carries no honest per-variable
    capability signal). Picking nearest-by-distance alone can therefore return a station that
    silently lacks the data the caller actually needs.

    `requires`, when given as a non-empty sequence of controlled-vocabulary variable names,
    makes nearest() verify capability the only honest way available: probe candidates
    nearest-first, calling the adapter's own `fetch()` over a short recent window, until one
    actually reports every required variable. `requires=None` (the default) is byte-for-byte
    today's behavior -- one `list_stations()` call, zero fetches, zero new network for existing
    callers.
    """
    if requires:
        bad = [name for name in requires if not vocab.is_variable(name)]
        if bad:
            raise ValueError(
                f"unknown variable name(s) in requires: {bad}; "
                f"known variables: {sorted(vocab.VARIABLES)}"
            )

    adapter = _adapter_for(source)
    stations = adapter.list_stations()
    if not stations:
        raise ValueError(f"no stations available from source {source!r}")
    stations = sorted(stations, key=lambda s: _haversine_km(lat, lon, s.lat, s.lon))

    if not requires:
        return stations[0]

    required = set(requires)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=probe_window_h)
    probed: list[tuple[str, float, str]] = []  # (station_id, distance_km, reason)
    for st in stations[:max_probes]:
        dist_km = _haversine_km(lat, lon, st.lat, st.lon)
        try:
            cf = adapter.fetch(st.station_id, start=start, end=end, variables=list(requires))
        except (AdapterFetchError, AdapterParseError) as e:
            probed.append((st.station_id, dist_km, f"{type(e).__name__}: {e}"))
            continue
        available = set(cf.data["variable"]) if not cf.data.empty else set()
        if required <= available:
            return st
        missing = sorted(required - available)
        probed.append((st.station_id, dist_km, f"missing: {', '.join(missing)}"))

    details = "; ".join(f"{sid} ({dist:.1f}km): {reason}" for sid, dist, reason in probed)
    raise AdapterFetchError(
        f"no station from source {source!r} passed the capability probe for "
        f"requires={sorted(required)} within {len(probed)} candidate(s): {details}"
    )


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_zip(zipcode, source="ndbc", country="us", requires=None,
                 max_probes=8, probe_window_h=6.0) -> Station:
    """Like nearest(), but you give a ZIP/postal code instead of lat/lon.

        nearest_zip("33139")   # Miami Beach -> closest station
        nearest_zip("33139", requires=("wave_height_significant",))  # closest WAVE-CAPABLE station
    Needs the optional 'pgeocode' package (see openmarina.geocode). `requires`/`max_probes`/
    `probe_window_h` pass straight through to nearest() -- see its docstring for the capability
    probe semantics.
    """
    lat, lon = zip_to_latlon(zipcode, country=country)
    # Pass the new kwargs through only when a caller actually uses them, so nearest_zip stays a
    # byte-for-byte passthrough of nearest(lat, lon, source) for pre-W9 callers (including any
    # test double patched against nearest()'s old 3-arg shape) when requires is not requested.
    if requires is None and max_probes == 8 and probe_window_h == 6.0:
        return nearest(lat, lon, source)
    return nearest(lat, lon, source, requires=requires,
                    max_probes=max_probes, probe_window_h=probe_window_h)
