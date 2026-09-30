import re
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Farm, FarmerProfile

_TAIL_RE = re.compile(r"_(?P<id1>\d+)_(?P<id2>\d+)_(?P<date>\d{4}-\d{2}-\d{2})\.gpx$", re.IGNORECASE)


@dataclass
class ParsedGpxFilename:
    last_name: str | None = None
    first_name: str | None = None
    middle_initial: str | None = None
    id1: str | None = None
    id2: str | None = None
    walk_date: str | None = None


@dataclass
class GpxMatchResult:
    farm: Farm | None = None
    farmer: FarmerProfile | None = None
    matched_by: str | None = None  # "farmers_id" | "farm_reference" | "name" | "name+middle_initial"
    candidates: list[FarmerProfile] = field(default_factory=list)


class GpxFarmerMatcherService:
    """
    Matches an uploaded GPX boundary-walk file to an existing farmer/farm using only
    the uploaded filename, e.g. "TAB_ABAO , JONEL  J._120961_1148107_2024-08-06.gpx".
    The two numeric IDs in the filename line up with PABS's FarmersID and FARMID
    formats and are tried first, since they're a more reliable signal than a name
    (real filenames have shown a filename middle-initial that disagrees with the
    farmer's actual middle name on file, so middle name/initial is only ever used
    as a tiebreaker between name candidates, never a hard requirement).
    """

    @staticmethod
    def parse_filename(filename: str) -> ParsedGpxFilename:
        tail = _TAIL_RE.search(filename)
        id1 = id2 = walk_date = None
        if tail:
            id1, id2, walk_date = tail.group("id1"), tail.group("id2"), tail.group("date")
            name_part = filename[: tail.start()]
        else:
            name_part = re.sub(r"\.gpx$", "", filename, flags=re.IGNORECASE)

        name_part = re.sub(r"^TAB_", "", name_part, flags=re.IGNORECASE)

        last_name = first_name = middle_initial = None
        if "," in name_part:
            last_raw, _, rest = name_part.partition(",")
            last_name = last_raw.strip() or None
            pieces = rest.strip().split()
            if pieces:
                first_name = pieces[0]
                if len(pieces) > 1:
                    middle_initial = pieces[-1].rstrip(".") or None

        return ParsedGpxFilename(
            last_name=last_name,
            first_name=first_name,
            middle_initial=middle_initial,
            id1=id1,
            id2=id2,
            walk_date=walk_date,
        )

    @classmethod
    def match(cls, filename: str, db: Session) -> GpxMatchResult:
        parsed = cls.parse_filename(filename)

        if parsed.id1:
            farmer = db.query(FarmerProfile).filter(FarmerProfile.farmers_id == parsed.id1).first()
            if farmer is not None:
                farm = cls._pick_farm(farmer, parsed, db)
                if farm is not None:
                    return GpxMatchResult(farm=farm, farmer=farmer, matched_by="farmers_id")

        if parsed.id2:
            farm = db.query(Farm).filter(Farm.csv_farm_reference == parsed.id2).first()
            if farm is not None:
                return GpxMatchResult(farm=farm, farmer=farm.farmer, matched_by="farm_reference")

        if parsed.last_name and parsed.first_name:
            candidates = (
                db.query(FarmerProfile)
                .filter(
                    func.lower(func.trim(FarmerProfile.last_name)) == parsed.last_name.strip().lower(),
                    func.lower(func.trim(FarmerProfile.first_name)) == parsed.first_name.strip().lower(),
                )
                .all()
            )
            if len(candidates) == 1:
                farm = cls._pick_farm(candidates[0], parsed, db)
                if farm is not None:
                    return GpxMatchResult(farm=farm, farmer=candidates[0], matched_by="name")
            elif len(candidates) > 1 and parsed.middle_initial:
                narrowed = [
                    c
                    for c in candidates
                    if c.middle_name and c.middle_name.strip().lower().startswith(parsed.middle_initial.lower())
                ]
                if len(narrowed) == 1:
                    farm = cls._pick_farm(narrowed[0], parsed, db)
                    if farm is not None:
                        return GpxMatchResult(farm=farm, farmer=narrowed[0], matched_by="name+middle_initial")
            if len(candidates) > 1:
                return GpxMatchResult(candidates=candidates)

        return GpxMatchResult()

    @staticmethod
    def _pick_farm(farmer: FarmerProfile, parsed: ParsedGpxFilename, db: Session) -> Farm | None:
        farms = db.query(Farm).filter(Farm.farmer_id == farmer.farmer_id).all()
        if not farms:
            return None
        if parsed.id2:
            for farm in farms:
                if farm.csv_farm_reference == parsed.id2:
                    return farm
        return farms[0] if len(farms) == 1 else None
