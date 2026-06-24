"""Tests for core types (ADAPTER_INTERFACE sections 2-4)."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import openmarina as om


def test_reexports_present():
    for n in ["Station", "Capabilities", "CanonicalFrame", "SourceAdapter",
              "BridgeError", "AdapterFetchError", "AdapterParseError",
              "VocabularyError", "QC_FLAGS"]:
        assert hasattr(om, n)


def test_exception_hierarchy():
    assert issubclass(om.AdapterFetchError, om.BridgeError)
    assert issubclass(om.AdapterParseError, om.BridgeError)
    assert issubclass(om.VocabularyError, om.BridgeError)


def test_station_frozen_and_tuple_variables():
    s = om.Station("ndbc:41122", 25.9, -89.7, "Western Gulf",
                   ["wave_height_significant", "wind_speed"])
    assert isinstance(s.variables, tuple)
    with pytest.raises(Exception):
        s.lat = 0.0  # frozen


def test_capabilities_defaults():
    c = om.Capabilities("ndbc", ["wind_speed"])
    assert c.requires_auth is False
    assert c.max_range_days is None
    assert isinstance(c.variables, tuple)


def test_source_adapter_protocol_isinstance():
    class Dummy:
        source_id = "ndbc"
        def list_stations(self): return []
        def fetch(self, station_id, start, end, variables=None): return None
        def capabilities(self): return None

    class Missing:  # no fetch
        source_id = "x"
        def list_stations(self): return []
        def capabilities(self): return None

    assert isinstance(Dummy(), om.SourceAdapter)
    assert not isinstance(Missing(), om.SourceAdapter)


def test_canonicalframe_empty_schema():
    cf = om.CanonicalFrame.empty(meta={"provenance": "t"})
    assert tuple(cf.data.columns) == om.CanonicalFrame.COLUMNS
    assert str(cf.data["timestamp"].dtype) == "datetime64[ns, UTC]"
    assert len(cf) == 0


def _sample_long():
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(2):
        ts = t0 + timedelta(hours=i)
        for var, val, unit in [("wave_height_significant", 1.2 + i, "m"),
                               ("wind_speed", 5.0 + i, "m/s")]:
            rows.append(dict(timestamp=ts, source="ndbc", station_id="ndbc:41122",
                             lat=25.9, lon=-89.7, variable=var, value=val,
                             unit=unit, qc_flag="good"))
    return om.CanonicalFrame(pd.DataFrame(rows), meta={"provenance": "t"})


def test_to_wide_roundtrip():
    cf = _sample_long()
    w = cf.to_wide()
    assert {"wave_height_significant", "wind_speed"}.issubset(w.columns)
    assert len(w) == 2 and len(cf) == 4


def test_to_wide_include_qc():
    cf = _sample_long()
    wq = cf.to_wide(include_qc=True)
    assert "wind_speed__qc" in wq.columns
