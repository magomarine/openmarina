"""SignalK delta conversion -- unit conversions, path mapping, qc filtering. Offline."""
import math
from datetime import datetime, timezone

import pandas as pd

import openmarina as om
from openmarina import signalk as sk
from openmarina import GroupReading, Summary
from openmarina import vocabulary as vocab

T0 = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)


def _cf(rows):
    recs = [
        dict(timestamp=t, source="fake", station_id=sid, lat=0.0, lon=0.0,
             variable=v, value=val, unit=vocab.unit_for(v), qc_flag=qc)
        for (sid, v, val, qc, t) in rows
    ]
    df = pd.DataFrame(recs, columns=list(om.CanonicalFrame.COLUMNS))
    return om.CanonicalFrame(df, meta={})


def _paths(delta):
    return {v["path"]: v["value"] for v in delta["updates"][0]["values"]}


def test_every_mapped_variable_is_in_the_vocabulary():
    for name in sk.SIGNALK_PATHS:
        assert vocab.is_variable(name), name


def test_unit_conversions_deg_to_rad_and_c_to_k():
    cf = _cf([
        ("ndbc:x", "wind_direction", 90.0, "good", T0),
        ("ndbc:x", "water_temperature", 20.0, "good", T0),
        ("ndbc:x", "wind_speed", 5.0, "good", T0),
        ("ndbc:x", "air_pressure", 101325.0, "good", T0),
    ])
    (delta,) = sk.frame_to_deltas(cf)
    p = _paths(delta)
    assert math.isclose(p["environment.wind.directionTrue"], math.pi / 2)
    assert math.isclose(p["environment.water.temperature"], 293.15)
    assert p["environment.wind.speedTrue"] == 5.0            # already SI, passthrough
    assert p["environment.outside.pressure"] == 101325.0     # already SI, passthrough


def test_non_good_rows_are_dropped():
    cf = _cf([
        ("ndbc:x", "wind_speed", 5.0, "good", T0),
        ("ndbc:x", "wind_gust", 99.0, "suspect", T0),
    ])
    (delta,) = sk.frame_to_deltas(cf)
    assert "environment.wind.gust" not in _paths(delta)


def test_one_delta_per_station_timestamp_oldest_first():
    cf = _cf([
        ("ndbc:x", "wind_speed", 6.0, "good", T1),
        ("ndbc:x", "wind_speed", 5.0, "good", T0),
        ("coops:y", "water_level", 0.4, "good", T0),
    ])
    deltas = sk.frame_to_deltas(cf)
    assert len(deltas) == 3
    stamps = [d["updates"][0]["timestamp"] for d in deltas]
    assert stamps == sorted(stamps)
    srcs = {d["updates"][0]["source"]["src"] for d in deltas}
    assert srcs == {"ndbc:x", "coops:y"}


def test_source_block_names_openmarina_and_station():
    cf = _cf([("ndbc:x", "wind_speed", 5.0, "good", T0)])
    (delta,) = sk.frame_to_deltas(cf, context="vessels.self")
    assert delta["context"] == "vessels.self"
    assert delta["updates"][0]["source"] == {"label": "openmarina", "src": "ndbc:x"}


def test_summary_to_deltas_one_per_group_skipping_none():
    s = Summary(lat=0.0, lon=0.0, groups={
        "wave": GroupReading(
            group="wave", station_id="ndbc:b", station_name="buoy",
            lat=0.4, lon=0.0, distance_km=44.0, time=T0,
            values={"wave_height_significant": 1.2, "wave_direction": 180.0},
            units={"wave_height_significant": "m", "wave_direction": "deg"},
        ),
        "tide": None,
    })
    (delta,) = sk.summary_to_deltas(s)
    p = _paths(delta)
    assert p["environment.wave.significantHeight"] == 1.2
    assert math.isclose(p["environment.wave.direction"], math.pi)
    assert delta["updates"][0]["source"]["src"] == "ndbc:b"


def test_empty_frame_yields_no_deltas():
    assert sk.frame_to_deltas(om.CanonicalFrame.empty()) == []
