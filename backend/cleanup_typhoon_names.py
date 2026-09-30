"""
One-off cleanup for `tbl_typhoons` rows created before the name-parsing fix in
`app/services/bulletin_parser.py`'s `parse_bulletin_text()`. That bug let an
unquoted storm name in the source PDF run on into the following text (e.g.
"GARDO Issued at" instead of "GARDO"), so any typhoon parsed before the fix
may have a corrupted name.

For each Typhoon row, this derives the "clean" name (the same single-word
bound the fixed regex now enforces) and:
  - if a clean-named Typhoon row already exists for that name, re-points the
    corrupted row's bulletins to it and deletes the now-empty corrupted row;
  - otherwise, renames the corrupted row in place.

Run once, manually, after applying the bulletin_parser.py fix:
    python cleanup_typhoon_names.py
"""

import re

from app.core.database import SessionLocal
from app.models.models import Typhoon, TropicalCycloneBulletin

_CLEAN_NAME_RE = re.compile(r"[A-Za-z][A-Za-z\-]*")


def clean_name_for(raw_name: str) -> str:
    match = _CLEAN_NAME_RE.match(raw_name.strip())
    return match.group(0).upper() if match else raw_name.strip().upper()


def main() -> None:
    db = SessionLocal()
    try:
        typhoons = db.query(Typhoon).all()
        renamed, merged = 0, 0

        for typhoon in typhoons:
            clean = clean_name_for(typhoon.name)
            if clean == typhoon.name:
                continue  # already clean

            canonical = (
                db.query(Typhoon)
                .filter(Typhoon.name == clean, Typhoon.typhoon_id != typhoon.typhoon_id)
                .first()
            )

            if canonical:
                moved = (
                    db.query(TropicalCycloneBulletin)
                    .filter(TropicalCycloneBulletin.typhoon_id == typhoon.typhoon_id)
                    .update({TropicalCycloneBulletin.typhoon_id: canonical.typhoon_id})
                )
                db.delete(typhoon)
                print(f"Merged Typhoon {typhoon.typhoon_id!r} ({typhoon.name!r}) "
                      f"into {canonical.typhoon_id!r} ({canonical.name!r}) — moved {moved} bulletin(s).")
                merged += 1
            else:
                print(f"Renamed Typhoon {typhoon.typhoon_id!r}: {typhoon.name!r} -> {clean!r}")
                typhoon.name = clean
                renamed += 1

        db.commit()
        print(f"Done. {renamed} row(s) renamed, {merged} row(s) merged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
