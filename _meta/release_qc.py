#!/usr/bin/env python3
"""release_qc.py v0.1 - openmarina release gate.

Why this exists: on 2026-08-12 an audit found the README documenting
`summary_zip()` and `signalk.summary_to_deltas()` while `pip install openmarina`
still served 0.0.1, which has neither. Following the README produced an
AttributeError. The docs had moved; the release had not.

This gate makes that class of drift impossible to ship: every public symbol and
CLI subcommand the README shows must exist in the package being released, and
the version must agree across pyproject / __init__ / CHANGELOG.

Output is ASCII only on purpose - a cp949/cp1252 Windows console mangles
non-ASCII and turns a real failure into a UnicodeEncodeError (see DEV-015 T3).

usage:
  python _meta/release_qc.py            # check the source tree
  python _meta/release_qc.py --dist      # also check built artifacts in dist/
"""
from __future__ import annotations
import re, sys, subprocess, importlib, pathlib, zipfile, tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
results: list[tuple[str, str, bool, str]] = []


def check(cid: str, name: str, ok: bool, detail: str = "") -> None:
    results.append((cid, name, ok, detail))


def read(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


def report() -> None:
    width = max(len(r[1]) for r in results)
    print("release_qc v0.1 - openmarina")
    for cid, name, ok, detail in results:
        print("  %s %-*s %s   %s" % (cid, width, name, "PASS" if ok else "FAIL", detail))
    npass = sum(1 for r in results if r[2])
    print("  verdict: %d/%d" % (npass, len(results)))
    print("  (founder review separately: prose quality, example usefulness)")


def main() -> int:
    readme = read("README.md")

    # --- versions -----------------------------------------------------------
    pyproj = read("pyproject.toml")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproj, re.M)
    v_proj = m.group(1) if m else "?"

    sys.path.insert(0, str(ROOT / "src"))
    for mod in [k for k in list(sys.modules) if k.startswith("openmarina")]:
        del sys.modules[mod]
    # A gate that dies on the failure it exists to catch reports nothing at all.
    # Import errors must come back as FAIL, not as a traceback.
    try:
        om = importlib.import_module("openmarina")
        import_err = ""
    except Exception as exc:
        om = None
        import_err = "%s: %s" % (type(exc).__name__, exc)
    check("R0", "package imports", om is not None, import_err or "ok")
    if om is None:
        report()
        return 1
    v_init = getattr(om, "__version__", "?")

    chg = read("CHANGELOG.md") if (ROOT / "CHANGELOG.md").exists() else ""
    m = re.search(r"^##\s*\[([^\]]+)\]", chg, re.M)
    v_chg = m.group(1) if m else "?"

    check("R1", "version agrees: pyproject / __init__ / CHANGELOG",
          v_proj == v_init == v_chg,
          "pyproject=%s __init__=%s CHANGELOG=%s" % (v_proj, v_init, v_chg))

    # --- README public API --------------------------------------------------
    syms = sorted(set(re.findall(r"\bopenmarina\.([A-Za-z_][\w]*)", readme)))
    missing = [s for s in syms if not hasattr(om, s)]
    check("R2", "README symbols exist in package", not missing,
          "checked %d: %s" % (len(syms), ", ".join(syms)) +
          ("" if not missing else " | MISSING: " + ", ".join(missing)))

    # --- README CLI subcommands --------------------------------------------
    cli_cmds = sorted(set(re.findall(r"^\s*openmarina\s+([a-z][a-z-]*)", readme, re.M)))
    cli_src = read("src/openmarina/cli.py")
    known = set(re.findall(r'add_parser\(\s*"([a-z][a-z-]*)"', cli_src))
    unknown = [c for c in cli_cmds if c not in known]
    check("R3", "README CLI subcommands exist", not unknown,
          "checked %d: %s" % (len(cli_cmds), ", ".join(cli_cmds)) +
          ("" if not unknown else " | UNKNOWN: " + ", ".join(unknown)))

    # --- stale release language --------------------------------------------
    stale = [p for p in ("once published", "not yet released", "coming soon",
                         "not published yet") if p in readme.lower()]
    check("R4", "no unpublished-state language in README", not stale,
          "found: " + ", ".join(stale) if stale else "clean")

    # --- CHANGELOG has an entry for this version ---------------------------
    check("R5", "CHANGELOG has an entry for %s" % v_proj,
          ("[%s]" % v_proj) in chg, "")

    # --- built artifacts ----------------------------------------------------
    if "--dist" in sys.argv:
        dist = ROOT / "dist"
        files = sorted(dist.glob("*")) if dist.exists() else []
        want = {"openmarina/_summary.py", "openmarina/signalk.py"}
        seen: set[str] = set()
        for f in files:
            if f.suffix == ".whl":
                seen |= {n for n in zipfile.ZipFile(f).namelist()}
            elif f.name.endswith(".tar.gz"):
                seen |= {"/".join(n.split("/")[1:]) for n in tarfile.open(f).getnames()}
        have_v = [f.name for f in files if v_proj in f.name]
        check("R6", "dist/ artifacts carry version %s" % v_proj, bool(have_v),
              ", ".join(f.name for f in files) or "dist/ empty")
        missing_mod = [w for w in want
                       if not any(s.endswith(w) or s.endswith("src/" + w) for s in seen)]
        check("R7", "dist/ artifacts contain the modules README documents",
              not missing_mod and bool(seen),
              "missing: " + ", ".join(missing_mod) if missing_mod else "ok")

    report()
    return 0 if all(r[2] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
