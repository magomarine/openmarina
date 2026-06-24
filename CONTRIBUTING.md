# Contributing to openmarina

Thanks for helping build the open marina. The project grows mainly one way: **someone adds a data
source.** That path is meant to take about **15 minutes** once the library surface is in place.

## TL;DR

1. Fork, clone, `pip install -e ".[dev]"`.
2. Add an adapter under `src/openmarina/adapters/` implementing the `SourceAdapter` contract.
3. Map the agency's fields to the **controlled vocabulary** (never invent variable names).
4. Add a small fixture (a captured sample response) under `tests/`.
5. Run the **conformance harness** -- if it's green, your adapter is valid by definition.
6. Open one PR. Sign your commits (`git commit -s`, DCO).

## The 15-minute "add a data source" path

> The contract lives in `ADAPTER_INTERFACE`; the variable namespace lives in the controlled
> vocabulary module (`openmarina.vocabulary`). Both are imported, never copied.

**1. Create the adapter.** One file per agency, e.g. `src/openmarina/adapters/cbibs.py`. An adapter
holds its own state (base URL, API key, cache) and implements three methods:

```python
class CbibsAdapter:                 # structural -- no base class to inherit
    def list_stations(self) -> list[Station]: ...
    def capabilities(self) -> Capabilities: ...
    def fetch(self, station_id, start, end, variables=None) -> CanonicalFrame: ...
```

Because the contract is a `typing.Protocol`, you don't subclass anything -- implement the three
methods and you're an adapter.

**2. Map fields to the controlled vocabulary.** For each value the agency reports, map it to a
canonical variable name and convert to its **SI unit** (e.g. hPa -> Pa, knots -> m/s). Respect the
direction conventions: wind/wave direction = "from", current direction = "to", degrees 0-360
clockwise from true north. If the agency reports something not yet in the vocab, add the variable to
`openmarina.vocabulary` in the same PR (name + SI unit + meaning + a sanity bound) -- that's how the
vocabulary grows.

**3. Handle failures on the right channel.** Raise `AdapterFetchError` for retryable network/transport
failures, `AdapterParseError` for malformed responses (not retryable). For *data-quality* problems
(missing/suspect values), don't raise -- set the row's `qc_flag` (`good` / `suspect` / `missing` /
`unverified`). The agency's range caps and pagination are **your** job: the core asks for a clean
start-end; the adapter chunks internally.

**4. Add a fixture.** Capture one real sample response and commit it under `tests/fixtures/<source>/`.
This lets the harness validate your mapping without hitting the network in CI.

**5. Run the conformance harness.**

```bash
pytest
```

The harness checks the things that make "add an agency = one PR" actually hold: every `variable` is
in the controlled vocab, declared `unit` is the SI unit for that dimension, directions are 0-360 with
the correct from/to convention, `water_level` rows carry a `datum`, values fall within physical
bounds, and so on. Green harness = valid adapter.

**6. Open one PR.** Keep it to a single source. Describe the agency, its auth (if any), and link the
fixture.

## Sign your work (DCO)

openmarina uses the [Developer Certificate of Origin](DCO.txt). Add a sign-off line to each commit:

```bash
git commit -s -m "Add CBIBS adapter"
```

This appends `Signed-off-by: Your Name <you@example.com>` and certifies you have the right to submit
the contribution under Apache-2.0. (This is a lightweight DCO sign-off -- **not** a separate
contributor agreement. The proprietary-data world-model track is governed separately and does not
apply to this public-data repo.)

## Scope

In scope: a free bridge over **public** marine data (NOAA/NDBC, CBIBS, tides & currents, ...). Out of
scope here: payments, a paid data marketplace, or any proprietary motion/prediction data. PRs that
drift toward those will be redirected, not merged.

## Style

- Python 3.10+, type hints throughout.
- `ruff` for lint/format, `mypy` for types, `pytest` for tests. Run all three before opening a PR.
- Small, focused PRs. One source, one concern.

## Code of conduct

Be decent. Assume good faith, keep critique technical, welcome newcomers -- the whole point is a
commons that's easy to join.
