"""ZIP / postal code -> (lat, lon).

Optional feature. Uses `pgeocode` (covers US + many countries; downloads & caches a
small dataset on first use). Kept optional so the core library has zero extra deps:
install with `pip install pgeocode` or `pip install openmarina[geo]`.
"""

from __future__ import annotations

import math

from openmarina.types import BridgeError


def zip_to_latlon(zipcode, country: str = "us") -> tuple[float, float]:
    """Return (lat, lon) for a postal code. Raises BridgeError if pgeocode is missing,
    ValueError if the postal code is unknown."""
    try:
        import pgeocode
    except ModuleNotFoundError as e:
        raise BridgeError(
            "ZIP lookup needs the optional 'pgeocode' package: "
            "pip install pgeocode   (or: pip install openmarina[geo])"
        ) from e

    rec = pgeocode.Nominatim(country).query_postal_code(str(zipcode).strip())
    lat, lon = rec.latitude, rec.longitude
    if lat is None or lon is None or (isinstance(lat, float) and math.isnan(lat)):
        raise ValueError(f"unknown postal code: {zipcode!r} (country={country!r})")
    return float(lat), float(lon)
