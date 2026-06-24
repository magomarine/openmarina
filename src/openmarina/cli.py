"""Command-line interface for openmarina.

After install, use it straight from the terminal:

    openmarina pull ndbc:41122 --wide -o miami.csv
    openmarina pull ndbc:41122 --vars wave_height_significant,wind_speed
    openmarina nearest 25.76 -80.19
    openmarina stations --source ndbc

Thin wrapper over the library (core.load / nearest); no logic of its own.
"""

from __future__ import annotations

import argparse
import sys

from openmarina import __version__, core


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openmarina", description="The open marina for maritime data.")
    p.add_argument("--version", action="version", version=f"openmarina {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pull = sub.add_parser("pull", help="pull one (or more) station's data")
    pull.add_argument("station_id", nargs="+", help="e.g. ndbc:41122 (one or more)")
    pull.add_argument("--start", default=None, help="ISO start, e.g. 2026-06-22T00:00Z")
    pull.add_argument("--end", default=None, help="ISO end")
    pull.add_argument("--vars", default=None, help="comma-separated variable names (default: all)")
    pull.add_argument("--wide", action="store_true", help="pivot to one column per variable")
    pull.add_argument("-o", "--out", default=None, help="write CSV to this file (default: stdout)")

    near = sub.add_parser("nearest", help="closest station to a lat/lon or ZIP code")
    near.add_argument("lat", type=float, nargs="?", help="latitude (or use --zip)")
    near.add_argument("lon", type=float, nargs="?", help="longitude (or use --zip)")
    near.add_argument("--zip", dest="zipcode", default=None, help="US/postal ZIP, e.g. 33139")
    near.add_argument("--country", default="us", help="country for --zip (default: us)")
    near.add_argument("--source", default="ndbc")

    st = sub.add_parser("stations", help="list stations for a source")
    st.add_argument("--source", default="ndbc")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "pull":
        variables = args.vars.split(",") if args.vars else None
        ids = args.station_id
        cf = (core.load(ids[0], args.start, args.end, variables) if len(ids) == 1
              else core.load_many(ids, args.start, args.end, variables))
        df = cf.to_wide() if args.wide else cf.data
        if args.out:
            df.to_csv(args.out, index=False)
            print(f"wrote {len(df)} rows -> {args.out}")
        else:
            print(df.to_string(index=False))

    elif args.cmd == "nearest":
        if args.zipcode:
            st = core.nearest_zip(args.zipcode, args.source, args.country)
        elif args.lat is not None and args.lon is not None:
            st = core.nearest(args.lat, args.lon, args.source)
        else:
            print("provide LAT LON or --zip ZIP", file=sys.stderr)
            return 2
        print(f"{st.station_id}  {st.name or ''}  ({st.lat}, {st.lon})")

    elif args.cmd == "stations":
        for s in core._adapter_for(args.source).list_stations():
            print(f"{s.station_id}\t{s.lat}\t{s.lon}\t{s.name or ''}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
