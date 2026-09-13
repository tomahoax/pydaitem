"""Lets `python -m pydaitem.cli` work, same as the installed `pydaitem` script."""

from __future__ import annotations

from . import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
