"""Enable `python -m openmarina ...` (reliable on locked-down machines where the
generated `openmarina.exe` shim is blocked or off-PATH)."""
from openmarina.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
