"""Adapter conformance harness — the executable spec (ADAPTER_INTERFACE §6).

Any adapter whose fetch() output passes this harness is, by definition, a valid adapter. The
frame-level checks (check_frame) also serve as a runtime validator for any CanonicalFrame.

The 10 checks: protocol, schema, vocab, unit, time, CRS, direction, datum, sanity, round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from openmarina import vocabulary as vocab
from openmarina.types import QC_FLAGS, CanonicalFrame, SourceAdapter

__all__ = ["CheckResult", "ConformanceReport", "check_frame", "check_adapter", "run_harness"]


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        tag = "PASS" if self.passed else "FAIL"
        return f"[{tag}] {self.name}" + (f" — {self.detail}" if self.detail else "")


@dataclass
class ConformanceReport:
    results: list

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def failures(self) -> list:
        return [r for r in self.results if not r.passed]

    def __str__(self) -> str:
        n = sum(r.passed for r in self.results)
        head = f"Conformance: {'PASS' if self.passed else 'FAIL'} ({n}/{len(self.results)})"
        return "\n".join([head] + [f"  {r}" for r in self.results])


def check_frame(cf: CanonicalFrame) -> list:
    """Checks 2–9 (+ qc validity) on a CanonicalFrame's data + meta."""
    out: list = []
    df = cf.data

    # 2 — schema: exact columns
    cols_ok = tuple(df.columns) == CanonicalFrame.COLUMNS
    out.append(CheckResult("schema/columns", cols_ok, "" if cols_ok else f"got {tuple(df.columns)}"))
    if not cols_ok:
        return out  # remaining checks assume the canonical columns

    ts_dtype = df["timestamp"].dtype
    ts_ok = str(ts_dtype).startswith("datetime64[ns") and getattr(ts_dtype, "tz", None) is not None
    out.append(CheckResult("schema/timestamp tz-aware UTC", ts_ok, "" if ts_ok else str(ts_dtype)))

    if df.empty:
        out.append(CheckResult("non-empty sample", False, "frame has no rows — give a fixture with data"))
        return out

    # 3 — vocab: every variable is controlled
    bad_vars = sorted(set(df["variable"]) - set(vocab.VARIABLES))
    out.append(CheckResult("vocab/controlled names", not bad_vars, "" if not bad_vars else f"unknown: {bad_vars}"))

    # 4 — unit: declared unit is the SI unit for that variable
    unit_bad = [
        (v, u) for v, u in df[["variable", "unit"]].drop_duplicates().itertuples(index=False)
        if v in vocab.VARIABLES and u != vocab.unit_for(v)
    ]
    out.append(CheckResult("unit/SI matches variable", not unit_bad, "" if not unit_bad else str(unit_bad)))

    # 5 — time: no duplicate (station, variable, timestamp)
    dup = int(df.duplicated(subset=["station_id", "variable", "timestamp"]).sum())
    out.append(CheckResult("time/no duplicates", dup == 0, "" if dup == 0 else f"{dup} duplicate rows"))

    # 6 — CRS: valid WGS84
    crs_ok = bool(df["lat"].between(-90, 90).all() and df["lon"].between(-180, 180).all())
    out.append(CheckResult("crs/WGS84 range", crs_ok))

    # 7 — direction vars within 0–360
    dir_bad = []
    for v in df["variable"].unique():
        if v in vocab.VARIABLES and vocab.get(v).direction:
            if not df.loc[df["variable"] == v, "value"].between(0, 360).all():
                dir_bad.append(v)
    out.append(CheckResult("direction/0–360", not dir_bad, "" if not dir_bad else str(dir_bad)))

    # 8 — datum required when water_level present
    has_wl = bool((df["variable"] == "water_level").any())
    datum_ok = (not has_wl) or ("datum" in cf.meta)
    out.append(CheckResult("datum/water_level", datum_ok, "" if datum_ok else "water_level present but meta.datum missing"))

    # qc flags valid
    bad_qc = sorted(set(df["qc_flag"]) - set(QC_FLAGS))
    out.append(CheckResult("qc_flag/valid values", not bad_qc, "" if not bad_qc else str(bad_qc)))

    # 9 — sanity: 'good' values must be within physical bounds
    viol = sum(
        1 for v, val, q in df[["variable", "value", "qc_flag"]].itertuples(index=False)
        if v in vocab.VARIABLES and q == "good" and not vocab.in_bounds(v, float(val))
    )
    out.append(CheckResult("sanity/good values in bounds", viol == 0, "" if viol == 0 else f"{viol} good rows out of bounds"))
    return out


def check_adapter(adapter) -> list:
    """Check 1 (protocol) + capabilities sanity."""
    out = [CheckResult("protocol/SourceAdapter", isinstance(adapter, SourceAdapter))]
    try:
        caps = adapter.capabilities()
        ok = caps.source_id == adapter.source_id
        out.append(CheckResult("capabilities/source_id matches", ok,
                               "" if ok else f"{caps.source_id} != {adapter.source_id}"))
    except Exception as e:  # noqa: BLE001
        out.append(CheckResult("capabilities/callable", False, repr(e)))
    return out


def run_harness(adapter, sample_frame: CanonicalFrame, expected: CanonicalFrame | None = None) -> ConformanceReport:
    """Full harness: adapter checks + frame checks (+ optional round-trip vs an expected frame).

    sample_frame is typically the adapter's parse of a bundled fixture (no network needed).
    """
    results = check_adapter(adapter) + check_frame(sample_frame)
    if expected is not None:
        same = sample_frame.data.reset_index(drop=True).equals(expected.data.reset_index(drop=True))
        results.append(CheckResult("round-trip/matches expected", bool(same)))
    return ConformanceReport(results)
