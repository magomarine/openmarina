"""Multi-station load (load_many) — offline via monkeypatched load."""
from datetime import datetime, timezone

import pandas as pd

import openmarina as om
from openmarina import core


def _cf_for(station_id):
    t = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [dict(timestamp=t, source="ndbc", station_id=station_id, lat=25.9, lon=-89.7,
                 variable="wave_height_significant", value=1.2, unit="m", qc_flag="good")]
    return om.CanonicalFrame(pd.DataFrame(rows), meta={"provenance": {"station": station_id}})


def test_load_many_concatenates(monkeypatch):
    monkeypatch.setattr(core, "load", lambda sid, *a, **k: _cf_for(sid))
    cf = core.load_many(["ndbc:41122", "ndbc:42040"])
    assert len(cf) == 2
    assert set(cf.data["station_id"]) == {"ndbc:41122", "ndbc:42040"}
    assert cf.meta["stations"] == ["ndbc:41122", "ndbc:42040"]


def test_load_many_to_wide_keeps_stations_apart(monkeypatch):
    monkeypatch.setattr(core, "load", lambda sid, *a, **k: _cf_for(sid))
    cf = core.load_many(["ndbc:41122", "ndbc:42040"])
    w = cf.to_wide()
    assert len(w) == 2  # one row per station
    assert "wave_height_significant" in w.columns
