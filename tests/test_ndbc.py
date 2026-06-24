"""NDBC adapter tests -- parser validated against a saved fixture (no network)."""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import openmarina as om
from openmarina import vocabulary as vocab
from openmarina.adapters.ndbc import NdbcAdapter

FIX = Path(__file__).parent / "fixtures" / "ndbc" / "41122.txt"
LAT, LON = 25.9, -89.7


def _parse():
    text = FIX.read_text()
    return NdbcAdapter._parse_met(text, "ndbc:41122", LAT, LON)


def test_adapter_is_source_adapter():
    assert isinstance(NdbcAdapter(), om.SourceAdapter)


def test_capabilities_no_network_static():
    caps = NdbcAdapter().capabilities()
    assert caps.source_id == "ndbc"
    assert caps.requires_auth is False
    assert "wave_height_significant" in caps.variables


def test_parser_schema_matches_canonical_columns():
    cf = _parse()
    assert tuple(cf.data.columns) == om.CanonicalFrame.COLUMNS
    assert str(cf.data["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_all_variables_in_vocabulary():
    cf = _parse()
    assert set(cf.data["variable"]).issubset(vocab.VARIABLES)


def test_units_are_si_for_each_variable():
    cf = _parse()
    for var, unit in cf.data[["variable", "unit"]].drop_duplicates().itertuples(index=False):
        assert unit == vocab.unit_for(var)


def test_unit_conversion_hpa_to_pa():
    cf = _parse()
    pres = cf.data[cf.data["variable"] == "air_pressure"]["value"]
    # fixture has 1013.2 hPa -> 101320 Pa
    assert pres.between(80000, 110000).all()
    assert abs(pres.iloc[0] - 101320.0) < 1.0 or abs(pres.max() - 101380.0) < 1.0


def test_missing_values_dropped():
    cf = _parse()
    # third fixture row has WSPD=MM and GST=MM -> wind_speed should have only 2 rows
    ws = cf.data[cf.data["variable"] == "wind_speed"]
    assert len(ws) == 2


def test_timestamps_utc_and_no_dupes():
    cf = _parse()
    d = cf.data
    assert d["timestamp"].dt.tz is not None
    assert not d.duplicated(subset=["station_id", "variable", "timestamp"]).any()


def test_provenance_present():
    cf = _parse()
    assert "provenance" in cf.meta
    assert cf.meta["provenance"]["agency"] == "NOAA NDBC"


def test_to_wide_from_real_parse():
    cf = _parse()
    w = cf.to_wide()
    assert "wave_height_significant" in w.columns
    assert len(w) == 3  # three timestamps in the fixture
