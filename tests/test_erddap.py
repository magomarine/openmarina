"""ERDDAP adapter — configurable; parser + harness validated on a fixture (no network)."""
import json
from pathlib import Path

import openmarina as om
from openmarina import conformance as conf, vocabulary as vocab
from openmarina.adapters.erddap import ErddapAdapter

FIX = Path(__file__).parent / "fixtures" / "erddap" / "buoy.json"


def _adapter():
    return ErddapAdapter("https://erddap.example", "buoy_dataset",
                         source_id="neracoos", station_col="station")


def _frame():
    obj = json.loads(FIX.read_text())
    a = _adapter()
    return ErddapAdapter._parse_table(obj, "neracoos:44098", a._var_map, "time",
                                      "latitude", "longitude", "station", "neracoos", None)


def test_is_source_adapter():
    assert isinstance(_adapter(), om.SourceAdapter)


def test_capabilities_from_var_map():
    caps = _adapter().capabilities()
    assert caps.source_id == "neracoos"
    assert "water_temperature" in caps.variables


def test_maps_cf_names_to_vocab():
    cf = _frame()
    got = set(cf.data["variable"])
    assert {"water_temperature", "air_temperature", "wind_speed", "wind_direction", "air_pressure"} <= got
    assert got.issubset(vocab.VARIABLES)


def test_unit_conversion_hpa_to_pa_and_station_from_column():
    cf = _frame()
    pres = cf.data[cf.data["variable"] == "air_pressure"]["value"].iloc[0]
    assert abs(pres - 101400.0) < 1.0          # 1014 hPa -> Pa
    assert set(cf.data["station_id"]) == {"neracoos:44098"}


def test_missing_values_skipped():
    cf = _frame()
    # row 3 has null sea_water_temperature and "" wind_speed -> 2 rows each
    assert (cf.data["variable"] == "water_temperature").sum() == 2
    assert (cf.data["variable"] == "wind_speed").sum() == 2


def test_frame_passes_conformance_harness():
    rep = conf.run_harness(_adapter(), _frame())
    assert rep.passed, str(rep)
