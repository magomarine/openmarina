"""NOAA CO-OPS adapter (adapter #2) — Tides & Currents.

US public-domain water-level, tides/currents, and met data from the CO-OPS Data API
(api.tidesandcurrents.noaa.gov). Complements NDBC with water_level (tides). No auth.

Each CO-OPS "product" is a separate API call with its own JSON shape; this adapter maps the
products we support into the controlled vocabulary. Response metadata carries lat/lon, so no
separate station lookup is needed for fetch(). Parser (_parse_product / _assemble) is pure and
fixture-tested; only fetch()/list_stations() touch the network.
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

DATA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
MDAPI_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

_ident = lambda x: x  # noqa: E731
_hpa_to_pa = lambda x: x * 100.0  # noqa: E731  (CO-OPS metric pressure = millibars = hPa)

# product -> list of (canonical_variable, json_field, converter-to-SI). units=metric.
_PRODUCT_FIELDS: dict[str, list] = {
    "water_level":       [("water_level", "v", _ident)],            # meters, needs datum
    "water_temperature": [("water_temperature", "v", _ident)],      # degC
    "air_temperature":   [("air_temperature", "v", _ident)],        # degC
    "air_pressure":      [("air_pressure", "v", _hpa_to_pa)],       # mbar -> Pa
    "wind":              [("wind_speed", "s", _ident),              # m/s
                          ("wind_direction", "d", _ident),         # deg (from)
                          ("wind_gust", "g", _ident)],             # m/s
}
# variable -> product (reverse), to pick which calls to make for a request
_VAR_TO_PRODUCT = {var: p for p, fields in _PRODUCT_FIELDS.items() for (var, _, _) in fields}
_ALL_VARIABLES = tuple(_VAR_TO_PRODUCT)


class CoopsAdapter:
    """SourceAdapter for NOAA CO-OPS. No auth; per-product API; metric units."""

    source_id = "coops"

    def __init__(self, session=None, timeout: float = 30.0, default_datum: str = "MLLW"):
        self._session = session
        self._timeout = timeout
        self._datum = default_datum

    # -- contract ----------------------------------------------------------- #
    def capabilities(self) -> Capabilities:
        return Capabilities(
            source_id=self.source_id,
            variables=_ALL_VARIABLES,
            max_range_days=31.0,        # 6-min products cap ~31 days/request; adapter could chunk (TODO)
            update_cadence_s=360.0,     # 6-min typical
            requires_auth=False,
        )

    def list_stations(self) -> list[Station]:
        obj = self._get_json(MDAPI_URL, {"type": "waterlevels"})
        try:
            out = []
            for s in obj.get("stations", []):
                sid, lat, lon = s.get("id"), s.get("lat"), s.get("lng")
                if sid is None or lat is None or lon is None:
                    continue
                out.append(Station(f"coops:{sid}", float(lat), float(lon), s.get("name"), _ALL_VARIABLES))
            return out
        except (TypeError, ValueError) as e:
            raise AdapterParseError(f"could not parse CO-OPS station list: {e}") from e

    def fetch(self, station_id, start=None, end=None, variables=None) -> CanonicalFrame:
        bare = station_id.split(":", 1)[-1]
        if start is None or end is None:
            raise AdapterFetchError("CO-OPS fetch requires start and end (it has no rolling realtime file)")
        products = self._products_for(variables)
        responses = {}
        for p in products:
            params = {
                "product": p, "application": "openmarina", "station": bare,
                "begin_date": _fmt(start), "end_date": _fmt(end),
                "units": "metric", "time_zone": "gmt", "format": "json",
            }
            if p == "water_level":
                params["datum"] = self._datum
            responses[p] = self._get_json(DATA_URL, params)
        return self._assemble(responses, f"coops:{bare}", self._datum)

    # -- pure parser (fixture-tested) --------------------------------------- #
    @staticmethod
    def _parse_product(product, obj, station_id):
        """Return (rows, lat, lon, has_water_level) for one product's JSON response."""
        if not isinstance(obj, dict) or "error" in obj:
            return [], None, None, False  # CO-OPS reports no-data via {"error": {...}}
        meta = obj.get("metadata") or {}
        try:
            lat, lon = float(meta["lat"]), float(meta["lon"])
        except (KeyError, TypeError, ValueError) as e:
            raise AdapterParseError(f"CO-OPS {product}: missing/invalid station metadata ({e})") from e
        rows, has_wl = [], False
        for d in obj.get("data", []):
            try:
                ts = pd.to_datetime(d["t"], utc=True)
            except (KeyError, ValueError) as e:
                raise AdapterParseError(f"CO-OPS {product}: bad timestamp ({e})") from e
            for var, key, conv in _PRODUCT_FIELDS[product]:
                raw = d.get(key, "")
                if raw in ("", None):
                    continue
                try:
                    val = float(conv(float(raw)))
                except (TypeError, ValueError):
                    continue  # unparseable single value -> treat as missing
                qc = "good" if vocab.in_bounds(var, val) else "suspect"
                if var == "water_level":
                    has_wl = True
                rows.append((ts, "coops", station_id, lat, lon, var, val, vocab.unit_for(var), qc))
        return rows, lat, lon, has_wl

    @classmethod
    def _assemble(cls, responses: dict, station_id: str, datum: str) -> CanonicalFrame:
        all_rows, has_wl = [], False
        for product, obj in responses.items():
            rows, _lat, _lon, wl = cls._parse_product(product, obj, station_id)
            all_rows.extend(rows)
            has_wl = has_wl or wl
        data = pd.DataFrame(all_rows, columns=list(CanonicalFrame.COLUMNS))
        if not data.empty:
            data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
            data = data.sort_values(["variable", "timestamp"]).reset_index(drop=True)
        meta = {
            "provenance": {"agency": "NOAA CO-OPS", "endpoint": DATA_URL, "station": station_id,
                           "retrieved_at": datetime.now(timezone.utc).isoformat()},
            "update_cadence_s": 360.0,
        }
        if has_wl:
            meta["datum"] = datum
        return CanonicalFrame(data=data, meta=meta)

    # -- helpers ------------------------------------------------------------ #
    def _products_for(self, variables):
        if not variables:
            return list(_PRODUCT_FIELDS)
        wanted = {_VAR_TO_PRODUCT[v] for v in variables if v in _VAR_TO_PRODUCT}
        return list(wanted) or list(_PRODUCT_FIELDS)

    def _get_json(self, url, params):
        try:
            if self._session is not None:
                r = self._session.get(url, params=params, timeout=self._timeout)
            else:
                import requests
                r = requests.get(url, params=params, timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — network failures are retryable
            raise AdapterFetchError(f"CO-OPS request failed for {url}: {e}") from e


def _fmt(dt) -> str:
    dt = pd.to_datetime(dt, utc=True)
    return dt.strftime("%Y%m%d %H:%M")
