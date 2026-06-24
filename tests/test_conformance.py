"""Conformance harness: passes on a valid (NDBC) frame, catches each violation."""
from pathlib import Path

import pandas as pd
import pytest

import openmarina as om
from openmarina import conformance as conf
from openmarina.adapters.ndbc import NdbcAdapter

FIX = Path(__file__).parent / "fixtures" / "ndbc" / "41122.txt"


def _ndbc_frame():
    return NdbcAdapter._parse_met(FIX.read_text(), "ndbc:41122", 25.9, -89.7)


def _names(results):
    return {r.name: r.passed for r in results}


# ---- positive: a real NDBC parse passes the whole harness ----
def test_ndbc_frame_passes_harness():
    rep = conf.run_harness(NdbcAdapter(), _ndbc_frame())
    assert rep.passed, str(rep)


def test_protocol_check_rejects_non_adapter():
    class NotAdapter:
        source_id = "x"
    results = conf.check_adapter(NotAdapter())
    assert _names(results)["protocol/SourceAdapter"] is False


# ---- negative: each broken frame fails the matching check ----
def _base_df():
    return _ndbc_frame().data.copy()


def test_catches_unknown_variable():
    df = _base_df()
    df.loc[df.index[0], "variable"] = "sea_vibes"
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["vocab/controlled names"] is False


def test_catches_wrong_unit():
    df = _base_df()
    df.loc[df["variable"] == "air_pressure", "unit"] = "hPa"  # should be Pa
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["unit/SI matches variable"] is False


def test_catches_duplicate_rows():
    df = _base_df()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["time/no duplicates"] is False


def test_catches_bad_latlon():
    df = _base_df()
    df.loc[df.index[0], "lat"] = 999.0
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["crs/WGS84 range"] is False


def test_catches_direction_out_of_range():
    df = _base_df()
    df.loc[df["variable"] == "wave_direction", "value"] = 400.0
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["direction/0–360"] is False


def test_catches_missing_datum_for_water_level():
    df = _base_df()
    row = df.iloc[[0]].copy()
    row["variable"] = "water_level"
    row["value"] = 0.5
    row["unit"] = "m"
    df2 = pd.concat([df, row], ignore_index=True)
    res = _names(conf.check_frame(om.CanonicalFrame(df2, {"provenance": {}})))  # no datum in meta
    assert res["datum/water_level"] is False


def test_catches_good_value_out_of_bounds():
    df = _base_df()
    i = df.index[df["variable"] == "wave_height_significant"][0]
    df.loc[i, "value"] = -5.0      # impossible
    df.loc[i, "qc_flag"] = "good"  # but flagged good -> violation
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["sanity/good values in bounds"] is False


def test_out_of_bounds_ok_if_flagged_suspect():
    df = _base_df()
    i = df.index[df["variable"] == "wave_height_significant"][0]
    df.loc[i, "value"] = -5.0
    df.loc[i, "qc_flag"] = "suspect"   # flagged, so allowed
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["sanity/good values in bounds"] is True


def test_catches_bad_qc_flag():
    df = _base_df()
    df.loc[df.index[0], "qc_flag"] = "great"
    res = _names(conf.check_frame(om.CanonicalFrame(df, {"provenance": {}})))
    assert res["qc_flag/valid values"] is False
