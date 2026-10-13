#!/usr/bin/env python3
"""Which species BirdNET-Pi has heard that no plate covers yet.

Reads BirdNET-Pi's birds.db read-only, counts each species at the server's
own confidence floor, and asks the plate index (plates/index.json, written by
fetch_plates.py) for each one, in the household's Region. A species with no
plate shows the typographic fallback, or a generated illustration if one is
kept in data/generated/.

Each missing species is printed with the file name to give its image in
server/local/images/, where fetch_plates.py picks it up by that name.

Usage:
    python scripts/missing_plates.py              # species with no plate
    python scripts/missing_plates.py --all        # every species heard, and its plate
    python scripts/missing_plates.py --db PATH    # another birds.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from featherframe import paths  # noqa: E402
from featherframe.config import Config, load_config  # noqa: E402
from featherframe.db import Database  # noqa: E402
from featherframe.names import SpeciesIndex  # noqa: E402
from featherframe.render.genart import slugify  # noqa: E402
from featherframe.service import CONFIDENCE_FLOOR  # noqa: E402


def heard(db_path: str, floor: float) -> list[dict]:
    """[{common, scientific, count, last}] for every species at or above
    `floor`, most heard first."""
    uri = f"file:{Path(db_path).expanduser()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT Com_Name AS common, Sci_Name AS scientific, COUNT(*) AS count, "
            "MAX(Date) AS last FROM detections WHERE Confidence >= ? "
            "GROUP BY Sci_Name ORDER BY count DESC", (floor,)).fetchall()
    return [dict(r) for r in rows]


def plate_text(match) -> str:
    if match is None:
        return ""
    vol = f"{match.volume_no}." if match.volume_no else ""
    return f"{match.folio} {vol}{match.plate_number}"


def main() -> int:
    ap = argparse.ArgumentParser(description="List species heard that have no plate.")
    ap.add_argument("--db", default=None, help="BirdNET-Pi's birds.db (default: the server's setting)")
    ap.add_argument("--region", default=None, help="Region to match in (default: the server's setting)")
    ap.add_argument("--all", action="store_true", help="list every species heard, with its plate")
    args = ap.parse_args()

    try:
        config = load_config(Database())
    except Exception:  # noqa: BLE001 — no server state yet: the defaults
        config = Config()
    db_path = args.db or config.birdnet_db_path
    region = args.region or config.region

    try:
        species = heard(db_path, CONFIDENCE_FLOOR)
    except sqlite3.Error as exc:
        print(f"Can't read {db_path}: {exc}")
        return 1
    if not paths.plate_index_path().exists():
        print(f"No plate index at {paths.plate_index_path()}. Run scripts/fetch_plates.py first.")
        return 1
    index = SpeciesIndex.load()
    generated = paths.generated_dir()

    missing = 0
    rows = []
    for s in species:
        match = index.match(s["common"], s["scientific"], region)
        if match is None:
            missing += 1
        elif not args.all:
            continue
        has_ai = (generated / f"{slugify(s['scientific'])}.png").exists()
        rows.append((s, match, has_ai))

    print(f"{len(species)} species heard at confidence {CONFIDENCE_FLOOR:.0%} or more "
          f"({db_path}), region {region}: {missing} with no plate.\n")
    for s, match, has_ai in rows:
        if match is not None:
            print(f"  {s['count']:>6}  {s['common']} ({s['scientific']}): {plate_text(match)}")
            continue
        shown = "generated illustration" if has_ai else "typographic fallback"
        print(f"  {s['count']:>6}  {s['common']} ({s['scientific']}), last {s['last']}: {shown}")
        print(f"          image: server/local/images/{s['scientific']}.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
