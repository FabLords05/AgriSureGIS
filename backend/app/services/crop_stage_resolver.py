import dataclasses
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import CropStageMapping

logger = logging.getLogger(__name__)


def normalize_stage_label(value: Any) -> str | None:
    """Collapses a 'Stage of Crop' value to the form tbl_crop_stage_mapping stores:
    lowercased, outer whitespace stripped, internal runs collapsed to one space.

    Deliberately does NOT strip '/' the way upload.py's _normalize_header() strips
    punctuation from column names -- the slash is meaningful here. PCIC's own merged
    labels ('panicle initiation/booting', 'vegetative/tillering') are distinct
    concepts from the single stages they join, and flattening them would collide
    'panicle initiation/booting' with nothing useful while losing the distinction
    that keeps the PI/BS pairing on hold.
    """
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().lower()
    return text or None


# PCIC's own stage names -> the legacy "Stage No." code they carry. The official
# Region III "List of Farms with GPX File" export (2026-10-22) writes "Stage of
# Crop" as e.g. 'Mn. Tl. Stg. (EARLY VEGETATIVE)' -- the legacy export's "Stage"
# column ('1 - Mn. Tl. Stg. (EARLY VEGETATIVE)') minus its "N - " prefix -- and
# leaves the code column blank. Codes 8/9 (HD/YR) are left out on purpose: their
# label has not appeared in any real file yet, so they stay unmapped and logged.
_PCIC_STAGE_LABEL_CODES: dict[str, int] = {
    "s/tstg": 0,
    "mntlstg": 1,
    "mxtlstg": 2,
    "pistg": 3,
    "bootingstg": 4,
    "floweringstg": 5,
    "milkingstg": 6,
    "doughstg": 7,
}


def pcic_label_to_code(value: Any) -> int | None:
    """'Booting Stg. (REPRODUCTIVE)' or '4 - Booting Stg. (REPRODUCTIVE)' -> 4.
    The trailing '(...)' group is ignored -- the code's tbl_crop_stage_mapping row
    is what decides the stage group, not the label's own wording."""
    label = normalize_stage_label(value)
    if label is None:
        return None
    label = re.sub(r"^\d+\s*-\s*", "", label)
    label = label.split("(", 1)[0]
    return _PCIC_STAGE_LABEL_CODES.get(re.sub(r"[^a-z0-9/]", "", label))


def coerce_stage_code(value: Any) -> int | None:
    """Coerces a legacy 'Stage No.' to int. pandas infers this column as int64,
    float64 (when any row is blank) or object depending on the file, so '4', 4,
    4.0 and numpy scalars all have to land on the same key.
    """
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


@dataclass(frozen=True)
class ResolvedCropStage:
    """What one CSV row's crop-stage column resolves to.

    `crop_stage_no` None means the row still ingests but is never assessed --
    AssessmentService's ELIGIBLE_CROP_STAGES check simply never matches None.
    `stage_group` is independent of it: a stage can be ineligible for a Table 11
    yield-loss row yet still carry a Table 1 group, and Milking carries a different
    group from Flowering despite sharing crop_stage_no 2.
    """

    crop_stage_no: int | None = None
    stage_group: str | None = None
    pcic_stage: str | None = None
    # "code" | "label" | None (nothing matched)
    matched_by: str | None = None

    @property
    def is_assessable(self) -> bool:
        return self.crop_stage_no is not None


UNRESOLVED = ResolvedCropStage()


class CropStageResolver:
    """In-memory view of tbl_crop_stage_mapping, loaded once per CSV upload.

    The table is ~17 rows, so this is one query per upload rather than per row --
    the same reasoning as upload.py's _prefetch_caches(), which loads this
    alongside its other per-upload lookups.
    """

    def __init__(self, by_code: dict[int, ResolvedCropStage], by_label: dict[str, ResolvedCropStage]):
        self._by_code = by_code
        self._by_label = by_label
        # Each distinct unmapped value is logged once per upload, not once per row --
        # a 1,100-row file with one unknown stage would otherwise emit 1,100 lines.
        self._warned: set[str] = set()

    @classmethod
    def load(cls, db: Session) -> "CropStageResolver":
        by_code: dict[int, ResolvedCropStage] = {}
        by_label: dict[str, ResolvedCropStage] = {}

        for row in db.query(CropStageMapping).filter(CropStageMapping.is_active.is_(True)).all():
            if row.source_code is not None:
                by_code[row.source_code] = ResolvedCropStage(
                    crop_stage_no=row.crop_stage_no,
                    stage_group=row.stage_group,
                    pcic_stage=row.pcic_stage,
                    matched_by="code",
                )
            label = normalize_stage_label(row.source_label)
            if label is not None:
                by_label[label] = ResolvedCropStage(
                    crop_stage_no=row.crop_stage_no,
                    stage_group=row.stage_group,
                    pcic_stage=row.pcic_stage,
                    matched_by="label",
                )

        if not by_code and not by_label:
            logger.warning(
                "tbl_crop_stage_mapping is empty -- every row will ingest with no crop "
                "stage and no assessment will ever fire. Re-apply init_schema.sql's seed "
                "or backend/migrations/2026-10-09_crop_stage_mapping.sql."
            )
        return cls(by_code, by_label)

    def resolve(self, *, stage_code: Any = None, stage_label: Any = None) -> ResolvedCropStage:
        """Resolves a row's crop stage from whichever column its CSV layout carries.

        The legacy export's integer code is tried first because it is the more
        specific signal -- it distinguishes PI from BS, which the newer export's
        merged 'panicle initiation/booting' label cannot. A file carrying both
        therefore gets the better answer.
        """
        code = coerce_stage_code(stage_code)
        if code is not None and code in self._by_code:
            return self._by_code[code]

        label = normalize_stage_label(stage_label)
        if label is not None and label in self._by_label:
            return self._by_label[label]

        # PCIC's long stage name ('Mn. Tl. Stg. (EARLY VEGETATIVE)') resolves
        # through the code it stands for, so eligibility and group still come
        # from that code's own mapping row.
        label_code = pcic_label_to_code(label)
        if label_code is not None and label_code in self._by_code:
            return dataclasses.replace(self._by_code[label_code], matched_by="label")

        if code is not None or label is not None:
            self._warn_unmapped(code if label is None else label)
        return UNRESOLVED

    def _warn_unmapped(self, value: Any) -> None:
        key = str(value)
        if key in self._warned:
            return
        self._warned.add(key)
        logger.warning(
            "Crop stage %r is not in tbl_crop_stage_mapping -- those rows will ingest "
            "but are never assessed. Add a mapping row if this stage should pay out.",
            value,
        )
