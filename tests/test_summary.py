"""summary() / summary_zip() -- offline, zero network.

Style matches test_core_nearest.py: a fake adapter injected via monkeypatch. The fake
serves BOTH sources (ndbc/coops) so per-group independent probing is exercised against
one canned station set.
"""
from datetime import datetime, timezone

import pandas as pd
import pytest

import openmarina as om
from openmarina import _summary as summ
from openmarina.types import AdapterFetchError, Station

T0 = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)


def _cf(station_id, rows):
    """rows: (variable, value, unit, qc_flag, timestamp) tuples -> CanonicalFrame."""
    recs = [
        dict(timestamp=t, source="fake", station_id=station_id, lat=0.0, lon=0.0,
             variable=v, value=val, unit=u, qc_flag=qc)
        for (v, val, u, qc, t) in rows
    ]
    df = pd.DataFrame(recs, columns=list(om.CanonicalFrame.COLUMNS)) if recs else om.CanonicalFrame.empty().data
    return om.CanonicalFrame(df, meta={"provenance": {"station": station_id}})


class FakeAdapter:
    def __init__(self, stations, responses):
        self._stations = stations
        self._responses = responses
        self.fetch_calls = []

    def list_stations(self):
        return list(self._stations)

    def fetch(self, station_id, start=None, end=None, variables=None):
        self.fetch_calls.append(station_id)
        resp = self._responses.get(station_id, _cf(station_id, []))
        if isinstance(resp, Exception):
            raise resp
        return resp

    def capabilities(self):
        raise NotImplementedError


# tidegauge ~2km away (tide only) · wavebuoy ~50km away (wave+wind+temp)
TIDEGAUGE = Station("fake:tidegauge", lat=0.02, lon=0.0, name="tidegauge",
                    variables=("water_level",))
WAVEBUOY = Station("fake:wavebuoy", lat=0.45, lon=0.0, name="wavebuoy",
                   variables=("wave_height_significant",))

BUOY_ROWS = [
    ("wave_height_significant", 1.2, "m", "good", T0),
    ("wave_period_dominant", 7.0, "s", "good", T0),
    ("wind_speed", 6.2, "m/s", "good", T0),
    ("wind_direction", 240.0, "deg", "good", T0),
    ("wind_gust", 8.8, "m/s", "good", T0),
    ("water_temperature", 29.5, "degree_celsius", "good", T0),
]
GAUGE_ROWS = [("water_level", 0.4, "m", "good", T0)]


def _install(monkeypatch, adapter):
    monkeypatch.setattr(summ, "_adapter_for", lambda source: adapter)


def _standard_adapter():
    return FakeAdapter(
        [TIDEGAUGE, WAVEBUOY],
        {"fake:tidegauge": _cf("fake:tidegauge", GAUGE_ROWS),
         "fake:wavebuoy": _cf("fake:wavebuoy", BUOY_ROWS)},
    )


def test_groups_come_from_independent_nearest_capable_stations(monkeypatch):
    _install(monkeypatch, _standard_adapter())
    s = summ.summary(0.0, 0.0)
    assert s.groups["tide"].station_id == "fake:tidegauge"      # nearest wins where capable
    assert s.groups["wave"].station_id == "fake:wavebuoy"       # probe skipped the tide gauge
    assert s.groups["wind"].station_id == "fake:wavebuoy"
    assert s.groups["wave"].values["wave_height_significant"] == 1.2
    assert s.groups["wave"].values["wave_period_dominant"] == 7.0   # optional harvested
    assert s.groups["wind"].values["wind_gust"] == 8.8
    assert s.groups["tide"].distance_km < s.groups["wave"].distance_km


def test_partial_success_is_normal(monkeypatch):
    adapter = FakeAdapter([WAVEBUOY], {"fake:wavebuoy": _cf("fake:wavebuoy", BUOY_ROWS)})
    _install(monkeypatch, adapter)
    s = summ.summary(0.0, 0.0)
    assert s.groups["tide"] is None
    assert s.groups["wave"] is not None


def test_all_groups_failing_raises(monkeypatch):
    adapter = FakeAdapter([TIDEGAUGE], {"fake:tidegauge": _cf("fake:tidegauge", [])})
    _install(monkeypatch, adapter)
    with pytest.raises(AdapterFetchError):
        summ.summary(0.0, 0.0)


def test_unknown_group_raises_value_error(monkeypatch):
    _install(monkeypatch, _standard_adapter())
    with pytest.raises(ValueError):
        summ.summary(0.0, 0.0, groups=("wave", "sharknado"))


def test_groups_subset_only_probes_requested(monkeypatch):
    adapter = _standard_adapter()
    _install(monkeypatch, adapter)
    s = summ.summary(0.0, 0.0, groups=("tide",))
    assert set(s.groups) == {"tide"}
    assert all(sid == "fake:tidegauge" for sid in adapter.fetch_calls)


def test_latest_good_skips_newer_suspect_rows(monkeypatch):
    rows = BUOY_ROWS + [("wave_height_significant", 9.9, "m", "suspect", T1)]
    adapter = FakeAdapter([WAVEBUOY], {"fake:wavebuoy": _cf("fake:wavebuoy", rows)})
    _install(monkeypatch, adapter)
    s = summ.summary(0.0, 0.0, groups=("wave",))
    assert s.groups["wave"].values["wave_height_significant"] == 1.2   # good beats newer suspect


def test_summary_zip_geocodes_then_delegates(monkeypatch):
    _install(monkeypatch, _standard_adapter())
    monkeypatch.setattr(summ, "zip_to_latlon", lambda zipcode, country="us": (0.0, 0.0))
    s = summ.summary_zip("33139")
    assert s.groups["tide"].station_id == "fake:tidegauge"


def test_to_dict_is_json_ready(monkeypatch):
    import json

    _install(monkeypatch, _standard_adapter())
    d = summ.summary(0.0, 0.0).to_dict()
    json.dumps(d)   # must not raise
    assert d["groups"]["wave"]["values"]["wave_height_significant"] == 1.2
