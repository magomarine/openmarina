"""openmarina -- the open marina for maritime data.

One clean Python interface over fragmented US public marine data. Every agency is a source
adapter implementing one contract (SourceAdapter); every adapter returns a CanonicalFrame whose
variables come from one controlled vocabulary (SI units, UTC, WGS84).

    import openmarina
    cf = openmarina.load("ndbc:41122")          # last 24h, clean
    df = cf.to_wide()                            # one column per variable

An open library for public marine data. Apache-2.0.
"""

__version__ = "0.0.1"

from openmarina.types import (
    AdapterFetchError,
    AdapterParseError,
    BridgeError,
    Capabilities,
    CanonicalFrame,
    QC_FLAGS,
    QCFlag,
    SourceAdapter,
    Station,
    VocabularyError,
)
from openmarina import conformance, vocabulary
from openmarina.core import load, load_many, nearest, nearest_zip

__all__ = [
    "__version__",
    "load",
    "load_many",
    "nearest",
    "nearest_zip",
    "vocabulary",
    "conformance",
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
