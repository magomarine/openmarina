"""Core data types and the source-adapter contract.

Implements ADAPTER_INTERFACE sections 2-4 exactly:
    - Station, Capabilities          (frozen dataclasses)
    - CanonicalFrame                 (long-format DataFrame + sidecar metadata, plus to_wide())
    - exception hierarchy            (BridgeError -> AdapterFetchError / AdapterParseError / VocabularyError)
    - SourceAdapter                  (typing.Protocol, runtime_checkable: 3 methods)

Design note (locked): CanonicalFrame.data is the canonical **long / tidy** shape -- one row per
(station, variable, timestamp) observation, exactly per MASTER_INDEX 2.3. `to_wide()` is a convenience
projection for analysis/dogfooding; long stays the source of truth so metadata, variable extensibility,
and the schema-standard goal are preserved.

Variable *names* are NOT defined here -- they come from openmarina.vocabulary (the controlled
vocabulary, the single source of truth). This module references the contract, not the namespace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, Sequence, runtime_checkable

import pandas as pd

__all__ = [
    "Station",
    "Capabilities",
    "CanonicalFrame",
    "SourceAdapter",
    "QCFlag",
    "QC_FLAGS",
    "BridgeError",
    "AdapterFetchError",
    "AdapterParseError",
    "VocabularyError",
]


# --------------------------------------------------------------------------- #
# Exception hierarchy (ADAPTER_INTERFACE section 4 -- the error contract)
# --------------------------------------------------------------------------- #
class BridgeError(Exception):
    """Base for all openmarina errors."""


class AdapterFetchError(BridgeError):
    """Network failure, timeout, or unreachable agency endpoint. Core MAY retry."""


class AdapterParseError(BridgeError):
    """Agency returned data but it could not be parsed/mapped (format changed,
    unexpected schema). Core should NOT blindly retry; surface to the maintainer."""


class VocabularyError(BridgeError):
    """Adapter emitted a variable name not in the controlled vocabulary.
    Enforced by the conformance harness."""


# --------------------------------------------------------------------------- #
# QC flags (per-row data-quality channel -- NOT exceptions)
# --------------------------------------------------------------------------- #
QCFlag = Literal["good", "suspect", "missing", "unverified"]
QC_FLAGS: frozenset[str] = frozenset({"good", "suspect", "missing", "unverified"})


# --------------------------------------------------------------------------- #
# Station -- what an agency offers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Station:
    """A single observation station.

    station_id is the canonical 'source:station' id, e.g. 'ndbc:41122'.
    `variables` lists the controlled-vocabulary variables this station provides.
    """

    station_id: str
    lat: float                       # WGS84 decimal degrees, -90..90
    lon: float                       # WGS84 decimal degrees, -180..180
    name: str | None = None
    variables: tuple[str, ...] = ()  # immutable; controlled-vocab names

    def __post_init__(self) -> None:
        # normalize an incoming list/sequence to a tuple so the dataclass stays hashable/immutable
        if not isinstance(self.variables, tuple):
            object.__setattr__(self, "variables", tuple(self.variables))


# --------------------------------------------------------------------------- #
# Capabilities -- what an adapter can do (static; no network I/O to obtain)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Capabilities:
    """Static description of a source. capabilities() must not do network I/O."""

    source_id: str                       # 'ndbc' -- stable, lowercase, snake_case
    variables: tuple[str, ...]           # controlled-vocab variables this source can emit
    max_range_days: float | None = None  # per-request range cap (None = unlimited); adapter chunks
    update_cadence_s: float | None = None
    requires_auth: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.variables, tuple):
            object.__setattr__(self, "variables", tuple(self.variables))


# --------------------------------------------------------------------------- #
# CanonicalFrame -- the universal return shape (long/tidy + sidecar meta)
# --------------------------------------------------------------------------- #
@dataclass
class CanonicalFrame:
    """The shape every fetch() returns: a long-format DataFrame plus sidecar metadata.

    data columns are fixed (MASTER_INDEX 2.3):
        timestamp(UTC) source(str) station_id(str) lat lon(WGS84)
        variable(controlled vocab) value(float, SI) unit(SI str)
        qc_flag(good/suspect/missing/unverified)

    meta keys (MASTER_INDEX 2.4):
        provenance        -- agency + endpoint + retrieval time (REQUIRED)
        datum             -- vertical reference; REQUIRED whenever water_level present
        update_cadence_s  -- nominal interval, mirrors Capabilities
    """

    data: pd.DataFrame
    meta: dict = field(default_factory=dict)

    #: canonical column order for data (the long/tidy schema)
    COLUMNS: tuple[str, ...] = (
        "timestamp",
        "source",
        "station_id",
        "lat",
        "lon",
        "variable",
        "value",
        "unit",
        "qc_flag",
    )

    # -- constructors ------------------------------------------------------- #
    @classmethod
    def empty(cls, meta: dict | None = None) -> "CanonicalFrame":
        """An empty CanonicalFrame with the correct columns -- handy for adapters
        that find no data in a window."""
        df = pd.DataFrame({c: pd.Series(dtype=cls._dtype_for(c)) for c in cls.COLUMNS})
        return cls(data=df, meta=dict(meta or {}))

    @staticmethod
    def _dtype_for(column: str) -> str:
        if column == "timestamp":
            return "datetime64[ns, UTC]"
        if column in ("lat", "lon", "value"):
            return "float64"
        return "object"

    # -- projections -------------------------------------------------------- #
    def to_wide(
        self,
        index: Sequence[str] = ("timestamp", "source", "station_id"),
        include_qc: bool = False,
    ) -> pd.DataFrame:
        """Pivot the long data to a wide analysis frame: one column per variable.

        Long stays canonical; this is a convenience for analysis and
        plotting. `unit` is dropped (wide is for analysis, not transport); pass
        include_qc=True to also get a '<variable>__qc' column per variable.

        Assumes (station, variable, timestamp) is unique -- the conformance harness
        guarantees this for any valid adapter.
        """
        idx = list(index)
        if self.data.empty:
            return pd.DataFrame(columns=idx)

        wide = self.data.pivot(index=idx, columns="variable", values="value")
        if include_qc:
            qc = self.data.pivot(index=idx, columns="variable", values="qc_flag")
            qc = qc.add_suffix("__qc")
            wide = wide.join(qc)
        wide = wide.reset_index()
        wide.columns.name = None
        return wide

    # -- introspection ------------------------------------------------------ #
    def __len__(self) -> int:
        return len(self.data)


# --------------------------------------------------------------------------- #
# SourceAdapter -- THE contract (ADAPTER_INTERFACE section 3)
# --------------------------------------------------------------------------- #
@runtime_checkable
class SourceAdapter(Protocol):
    """Every data source implements exactly this. Three methods, nothing more required.

    Structural (typing.Protocol): an object is a SourceAdapter if it has `source_id`
    plus the three methods -- no inheritance required. That low barrier is what makes
    "add an agency = one PR" hold.
    """

    source_id: str  # e.g. 'ndbc' -- stable, lowercase, snake_case

    def list_stations(self) -> list[Station]:
        """Available stations with lat/lon and the controlled-vocab variables each provides.
        Raises AdapterFetchError on network/source failure."""
        ...

    def fetch(
        self,
        station_id: str,
        start: datetime,                      # tz-aware UTC
        end: datetime,                        # tz-aware UTC
        variables: list[str] | None = None,   # None = all this station offers
    ) -> CanonicalFrame:
        """Pull one station over [start, end] and return the canonical (long) shape.
        Raises AdapterFetchError (network) / AdapterParseError (format); data-quality
        issues are expressed via qc_flag, never exceptions."""
        ...

    def capabilities(self) -> Capabilities:
        """Static description: variables, range cap, cadence, auth. Must NOT do network I/O."""
        ...
