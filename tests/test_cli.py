"""CLI smoke tests — offline via monkeypatched core functions."""
import pytest

import openmarina as om
from openmarina import cli, core
from datetime import datetime, timezone
import pandas as pd


def _cf():
    t = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = [dict(timestamp=t, source="ndbc", station_id="ndbc:41122", lat=25.9, lon=-89.7,
                 variable="wind_speed", value=5.0, unit="m/s", qc_flag="good")]
    return om.CanonicalFrame(pd.DataFrame(rows), meta={"provenance": {}})


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "openmarina" in capsys.readouterr().out


def test_pull_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(core, "load", lambda *a, **k: _cf())
    rc = cli.main(["pull", "ndbc:41122"])
    assert rc == 0
    assert "wind_speed" in capsys.readouterr().out


def test_pull_wide_to_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(core, "load", lambda *a, **k: _cf())
    out = tmp_path / "x.csv"
    rc = cli.main(["pull", "ndbc:41122", "--wide", "-o", str(out)])
    assert rc == 0 and out.exists()
    assert "wind_speed" in out.read_text()


def test_pull_multi_uses_load_many(monkeypatch, capsys):
    called = {}
    monkeypatch.setattr(core, "load_many", lambda ids, *a, **k: (_cf()))
    monkeypatch.setattr(core, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should use load_many")))
    rc = cli.main(["pull", "ndbc:41122", "ndbc:42040"])
    assert rc == 0


def test_nearest_by_zip(monkeypatch, capsys):
    from openmarina.types import Station
    monkeypatch.setattr(core, "nearest_zip",
                        lambda z, src="ndbc", country="us": Station("ndbc:vakf1", 25.7, -80.2, "VK", ()))
    rc = cli.main(["nearest", "--zip", "33139"])
    assert rc == 0
    assert "ndbc:vakf1" in capsys.readouterr().out


def test_nearest_requires_coords_or_zip(capsys):
    rc = cli.main(["nearest"])
    assert rc == 2
