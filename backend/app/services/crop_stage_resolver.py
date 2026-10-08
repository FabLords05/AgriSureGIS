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
