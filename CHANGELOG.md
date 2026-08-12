# Changelog

All notable changes to openmarina are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.2] — 2026-08-12

### Added
- `summary()` / `summary_zip()` — one call returns waves, wind, tide and temperature for an
  area. Each capability group is probed independently, so an offshore wave buoy and a harbour
  tide gauge can answer the same request; the result records which station answered and from
  how far away.
- `signalk.summary_to_deltas()` — Signal K delta JSON output, station-attributed.
- CLI: `openmarina summary` with `--zip`, `--json` and `--signalk`.

### Fixed
- README install line said `# once published` after the package had already been published.

## [0.0.1] — 2026-06-24

### Added
- First public release. `load()` / `load_many()` return a `CanonicalFrame`: one variable
  vocabulary, SI units, UTC, WGS84, and a `qc_flag` on every value.
- Adapters: NDBC, CO-OPS, ERDDAP (one configurable adapter for many providers).
- `nearest()` / `nearest_zip()` station lookup, with a capability filter (`requires=`).
- Conformance harness so a new adapter is verified against one shared contract.
- CLI: `pull`, `nearest`, `stations`.

[0.0.2]: https://github.com/magomarine/openmarina/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/magomarine/openmarina/releases/tag/v0.0.1
