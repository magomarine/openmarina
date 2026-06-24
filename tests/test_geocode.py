"""ZIP geocoding + nearest_zip wiring (offline; pgeocode network not exercised)."""
import pytest

import openmarina as om
from openmarina import core, geocode
from openmarina.types import Station


def test_zip_to_latlon_missing_dep_raises_bridgeerror(monkeypatch):
    # simulate pgeocode not installed
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "pgeocode":
            raise ModuleNotFoundError("No module named 'pgeocode'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(om.BridgeError):
        geocode.zip_to_latlon("33139")


def test_nearest_zip_calls_nearest_with_geocoded_coords(monkeypatch):
    monkeypatch.setattr(core, "zip_to_latlon", lambda z, country="us": (25.76, -80.19))
    captured = {}

    def fake_nearest(lat, lon, source="ndbc"):
        captured.update(lat=lat, lon=lon, source=source)
        return Station("ndbc:vakf1", lat, lon, "Virginia Key", ())

    monkeypatch.setattr(core, "nearest", fake_nearest)
    st = core.nearest_zip("33139")
    assert (captured["lat"], captured["lon"]) == (25.76, -80.19)
    assert st.station_id == "ndbc:vakf1"
