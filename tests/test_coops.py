"""CO-OPS adapter — parser + harness, validated against fixtures (no network)."""
import json
from pathlib import Path

import pytest

import openmarina as om
from openmarina import conformance as conf, vocabulary as vocab
from openmarina.adapters.coops import CoopsAdapter

FIXDIR = Path(__file__).parent / "fixtures" / "coops"


def _load(name):
    return json.loads((FIXDIR / name).read_text())


def _assembled():
    responses = {
        "water_level": _load("water_level.json"),
        "wind": _load("wind.json"),
        "air_pressure": _load("air_pressure.json"),
    }
    return CoopsAdapter._assemble(responses, "coops:8723214", "MLLW")


def test_adapter_is_source_adapter():
    assert isinstance(CoopsAdapter(), om.SourceAdapter)


def test_capabilities_static():
    caps = CoopsAdapter().capabilities()
    assert caps.source_id == "coops" and caps.requires_auth is False
    assert "water_level" in caps.variables


def test_parses_and_maps_to_vocab():
    cf = _assembled()
    assert set(cf.data["variable"]).issubset(vocab.VARIABLES)
    assert {"water_level", "wind_speed", "wind_direction", "wind_gust", "air_pressure"} <= set(cf.data["variable"])


def test_units_si_and_pressure_converted():
    cf = _assembled()
    pres = cf.data[cf.data["variable"] == "air_pressure"]["value"].iloc[0]
    assert abs(pres - 101320.0) < 1.0          # 1013.2 hPa -> Pa
    units = dict(cf.data[["variable", "unit"]].drop_duplicates().itertuples(index=False))
    assert units["water_level"] == "m" and units["wind_speed"] == "m/s"


def test_water_level_sets_datum():
    cf = _assembled()
    assert (cf.data["variable"] == "water_level").any()
    assert cf.meta.get("datum") == "MLLW"


def test_missing_values_skipped():
    cf = _assembled()
    # water_level fixture has 3 rows, one with empty value -> 2 emitted
    assert (cf.data["variable"] == "water_level").sum() == 2


def test_error_response_yields_no_rows():
    rows, lat, lon, wl = CoopsAdapter._parse_product("water_level", _load("error.json"), "coops:8723214")
    assert rows == [] and lat is None and wl is False


def test_coops_frame_passes_conformance_harness():
    rep = conf.run_harness(CoopsAdapter(), _assembled())
    assert rep.passed, str(rep)
