"""nearest() / nearest_zip() capability filter (W9) -- offline, zero network.

Style matches test_core_multi.py: a fake adapter injected via monkeypatch, no real
network I/O. The fake's fetch() returns per-station canned CanonicalFrames and counts calls.
"""
from datetime import datetime, timezone

import pandas as pd
import pytest

import openmarina as om
from openmarina import core
from openmarina.types import AdapterFetchError, Station


def _cf(station_id, variables, t=None):
    """A CanonicalFrame reporting exactly `variables` for station_id (empty if none)."""
    t = t or datetime(2026, 7, 6, tzinfo=timezone.utc)
    rows = [
        dict(timestamp=t, source="fake", station_id=station_id, lat=0.0, lon=0.0,
             variable=v, value=1.0, unit="m", qc_flag="good")
        for v in variables
    ]
    df = pd.DataFrame(rows, columns=list(om.CanonicalFrame.COLUMNS)) if rows else om.CanonicalFrame.empty().data
    return om.CanonicalFrame(df, meta={"provenance": {"station": station_id}})


class FakeAdapter:
    """Minimal SourceAdapter: list_stations() returns canned Stations; fetch() returns
    canned per-station CanonicalFrames (or raises) and counts calls."""

    source_id = "fake"

    def __init__(self, stations, responses):
        self._stations = stations
        self._responses = responses  # station_id -> CanonicalFrame | Exception instance
        self.fetch_calls = []

    def list_stations(self):
        return list(self._stations)

    def fetch(self, station_id, start=None, end=None, variables=None):
        self.fetch_calls.append(station_id)
        resp = self._responses.get(station_id, _cf(station_id, ()))
        if isinstance(resp, Exception):
            raise resp
        return resp

    def capabilities(self):
        raise NotImplementedError


def _install(monkeypatch, adapter):
    """Patch core._adapter_for to hand back this one fake instance regardless of source."""
    monkeypatch.setattr(core, "_adapter_for", lambda source: adapter)


# Station A: "tidegauge" ~2km away, only water_level.
# Station B: "wavebuoy" ~50km away, has wave_height_significant.
STATION_A = Station("fake:tidegauge", lat=0.02, lon=0.0, name="tidegauge", variables=("water_level",))
STATION_B = Station("fake:wavebuoy", lat=0.45, lon=0.0, name="wavebuoy",
                     variables=("wave_height_significant",))


def test_regression_nearest_auto_skips_tidegauge_for_wave_capable_buoy(monkeypatch):
    """The W9 bug: nearest-by-distance alone would return the tide gauge; requires= must
    skip it and return the farther wave-capable buoy instead."""
    adapter = FakeAdapter(
        stations=[STATION_A, STATION_B],
        responses={
            STATION_A.station_id: _cf(STATION_A.station_id, ("water_level",)),
            STATION_B.station_id: _cf(STATION_B.station_id, ("wave_height_significant",)),
        },
    )
    _install(monkeypatch, adapter)
    st = core.nearest(0.0, 0.0, source="fake", requires=("wave_height_significant",))
    assert st.station_id == STATION_B.station_id


def test_requires_none_is_plain_distance_zero_fetches(monkeypatch):
    adapter = FakeAdapter(stations=[STATION_A, STATION_B], responses={})
    _install(monkeypatch, adapter)
    st = core.nearest(0.0, 0.0, source="fake", requires=None)
    assert st.station_id == STATION_A.station_id
    assert adapter.fetch_calls == []


def test_unknown_variable_name_raises_value_error_zero_network(monkeypatch):
    adapter = FakeAdapter(stations=[STATION_A, STATION_B], responses={})
    _install(monkeypatch, adapter)
    with pytest.raises(ValueError):
        core.nearest(0.0, 0.0, source="fake", requires=("not_a_real_variable",))
    assert adapter.fetch_calls == []


def test_closest_candidate_fetch_error_is_skipped(monkeypatch):
    adapter = FakeAdapter(
        stations=[STATION_A, STATION_B],
        responses={
            STATION_A.station_id: AdapterFetchError("network blip"),
            STATION_B.station_id: _cf(STATION_B.station_id, ("wave_height_significant",)),
        },
    )
    _install(monkeypatch, adapter)
    st = core.nearest(0.0, 0.0, source="fake", requires=("wave_height_significant",))
    assert st.station_id == STATION_B.station_id
    assert adapter.fetch_calls == [STATION_A.station_id, STATION_B.station_id]


def test_no_candidate_passes_raises_with_station_ids_and_variable(monkeypatch):
    adapter = FakeAdapter(
        stations=[STATION_A, STATION_B],
        responses={
            STATION_A.station_id: _cf(STATION_A.station_id, ("water_level",)),
            STATION_B.station_id: _cf(STATION_B.station_id, ("water_level",)),  # neither passes
        },
    )
    _install(monkeypatch, adapter)
    with pytest.raises(AdapterFetchError) as excinfo:
        core.nearest(0.0, 0.0, source="fake", requires=("wave_height_significant",))
    msg = str(excinfo.value)
    assert STATION_A.station_id in msg
    assert STATION_B.station_id in msg
    assert "wave_height_significant" in msg


def test_max_probes_limits_fetch_calls(monkeypatch):
    stations = [
        Station(f"fake:s{i}", lat=0.01 * (i + 1), lon=0.0, name=f"s{i}", variables=("water_level",))
        for i in range(5)
    ]
    responses = {s.station_id: _cf(s.station_id, ("water_level",)) for s in stations}  # none pass
    adapter = FakeAdapter(stations=stations, responses=responses)
    _install(monkeypatch, adapter)
    with pytest.raises(AdapterFetchError):
        core.nearest(0.0, 0.0, source="fake", requires=("wave_height_significant",), max_probes=3)
    assert len(adapter.fetch_calls) == 3


def test_nearest_zip_passthrough(monkeypatch):
    adapter = FakeAdapter(
        stations=[STATION_A, STATION_B],
        responses={
            STATION_A.station_id: _cf(STATION_A.station_id, ("water_level",)),
            STATION_B.station_id: _cf(STATION_B.station_id, ("wave_height_significant",)),
        },
    )
    _install(monkeypatch, adapter)
    monkeypatch.setattr(core, "zip_to_latlon", lambda zipcode, country="us": (0.0, 0.0))
    st = core.nearest_zip("33139", source="fake", requires=("wave_height_significant",))
    assert st.station_id == STATION_B.station_id


def test_empty_frame_candidate_does_not_pass(monkeypatch):
    adapter = FakeAdapter(
        stations=[STATION_A, STATION_B],
        responses={
            STATION_A.station_id: _cf(STATION_A.station_id, ()),  # listed water_level, no data in window
            STATION_B.station_id: _cf(STATION_B.station_id, ("wave_height_significant",)),
        },
    )
    _install(monkeypatch, adapter)
    st = core.nearest(0.0, 0.0, source="fake", requires=("wave_height_significant",))
    assert st.station_id == STATION_B.station_id
    assert adapter.fetch_calls == [STATION_A.station_id, STATION_B.station_id]
