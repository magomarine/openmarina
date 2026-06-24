# openmarina

**Clean marine data in one line — no parsers, no unit conversions, no agency quirks.**

```python
import openmarina

cf = openmarina.load("ndbc:41122")     # a buoy off Florida, last 24h
df = cf.to_wide()                       # one clean column per variable
```

---

## The problem it solves

You want recent wave height and wind near a spot on the water. Simple — until you try.

One agency hands you whitespace-delimited text with a cryptic header. The next wants an API key and
returns JSON. Pressure is in hectopascals here, millibars there. Wind direction means "coming from"
in one feed and "going to" in another. Timestamps arrive in three different time zones. So you write a
parser — and patch it again next month when the format quietly changes. Then you need a second
agency, and you start over.

Public ocean data is free, but *using* it costs you days.

**openmarina does that work once, so you don't.** One call returns a clean, normalized table — the
same variable names, the same SI units, UTC, WGS84 — no matter which agency the data came from.

## How it works

- **Normalized once.** A wave height from a Florida buoy and one from a Maine buoy come back as the
  same variable, in the same units, in the same table.
- **Quality you can see.** Every value carries a `qc_flag` (good / suspect / missing), so you know
  what to trust.
- **Find what's near you.** `nearest(lat, lon)` — or `nearest --zip 33139`.
- **Add an agency in one PR.** Each source is a small adapter behind one shared contract, verified by
  a built-in conformance harness. New sources don't complicate the ones you already use.

## Get started

Install (Python 3.10+):
```bash
pip install openmarina        # once published
pip install -e ".[dev]"       # from a clone
```

From Python:
```python
import openmarina

cf = openmarina.load("coops:8723214", start="2026-06-23", end="2026-06-24")
cf.to_wide()                                        # tidy table, one column per variable
cf.meta                                             # provenance, datum, cadence
openmarina.load_many(["ndbc:41122", "ndbc:41009"])  # several stations at once
openmarina.nearest_zip("33139")                     # nearest station to a ZIP (pip install pgeocode)
```

From the terminal:
```bash
openmarina pull ndbc:41122 --wide -o out.csv
openmarina nearest 25.76 -80.19
openmarina stations
# on a locked-down machine, run any command as:  python -m openmarina ...
```

## Sources today

| Source | What it gives you |
|--------|-------------------|
| **NDBC** | NOAA buoys — waves, wind, water/air temperature, pressure |
| **CO-OPS** | NOAA Tides & Currents — water level, currents, met |
| **ERDDAP** | one configurable adapter for 60+ global providers |

New agencies are welcome — the 15-minute path is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE) — free to use, including commercially.
