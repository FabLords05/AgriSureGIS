import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, load_only

from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    ExposureInterval,
    RiskAssessment,
    TcbSignal,
    TropicalCycloneBulletin,
)

logger = logging.getLogger(__name__)

SIGNAL_LEVELS = (1, 2, 3, 4, 5)
# Consecutive bulletins further apart than this are still counted (PAGASA
# signals stay hoisted until a later bulletin lifts them), but the area is
# flagged so the stretch can be checked against PAGASA's own records.
LONG_GAP_HOURS = 12

METHODOLOGY_NOTE = (
    "Hours are estimated from PAGASA bulletin issuance times: a municipality's "
    "signal from one bulletin is taken to hold until the next bulletin of the "
    "same typhoon is issued. A signal is lifted when a later bulletin no longer "
    "lists the municipality, lists no wind signals, or is the final bulletin. "
    "A signal still hoisted in the latest bulletin is counted up to that "
    "bulletin's issue time and marked ongoing; nothing after it is counted "
    "until a later bulletin arrives. PAGASA does not publish per-municipality effective "
    "times, so these are not independently verified exposure durations."
)


@dataclass(frozen=True)
class BulletinSnapshot:
    """One bulletin's resolved signals: (province, municipality) -> (signal_level, island_group)."""

    tcb_id: int
    bulletin_count: int
    issued_at: datetime
    is_final: bool
    areas: dict[tuple[str, str], tuple[int, int]]


@dataclass
class Interval:
    signal_level: int
    start: datetime
    end: datetime
    start_tcb_id: int
    end_tcb_id: int

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class AreaExposure:
    province: str
    municipality: str
    island_group: int
    max_signal_level: int
    start: datetime
    end: datetime
    intervals: list[Interval] = field(default_factory=list)
    has_open_interval: bool = False
    has_long_gap: bool = False

    def hours_by_level(self) -> dict[int, Decimal]:
        """Per-level hours, each rounded to 0.01h. total_hours sums these
        rounded values so Total = Signal 1 + ... + Signal 5 holds exactly."""
        raw = {level: 0.0 for level in SIGNAL_LEVELS}
        for interval in self.intervals:
            raw[interval.signal_level] += interval.hours
        return {level: Decimal(str(round(hours, 2))) for level, hours in raw.items()}

    @property
    def total_hours(self) -> Decimal:
        return sum(self.hours_by_level().values(), Decimal("0"))

    @property
    def payout_hours(self) -> Decimal:
        return self.hours_by_level()[self.max_signal_level]


def build_area_exposures(snapshots: list[BulletinSnapshot]) -> dict[tuple[str, str], AreaExposure]:
    """
    Reconstructs every municipality's signal timeline from one typhoon's
    bulletins and accumulates hours per TCWS level. Pure -- no DB access.

    - Bulletins are ordered by (issued_at, bulletin_count); a repeated
      bulletin_count keeps only the last one given (the latest parse).
    - A municipality's signal from bulletin k holds from issued_at[k] until
      issued_at[k+1]. A change of level closes the old interval and opens a
      new one; being absent from a later bulletin, or that bulletin being the
      final one, lifts it at that bulletin's issued_at.
    - Every interval sits on the single per-typhoon bulletin timeline, so a
      municipality's intervals can never overlap or be counted twice.
      Returning to an earlier level adds to that level's hours.
    - A signal still open after the last bulletin is counted up to that
      bulletin's issued_at -- it is known to have held at least that long --
      and the area is flagged has_open_interval. Nothing past the last
      bulletin is counted; the next recompute extends it.
    - Bulletins with the same issued_at produce no zero-length intervals.
    """
    by_count: dict[int, BulletinSnapshot] = {}
    for snapshot in snapshots:
        by_count[snapshot.bulletin_count] = snapshot
    ordered = sorted(by_count.values(), key=lambda s: (s.issued_at, s.bulletin_count))

    areas: dict[tuple[str, str], AreaExposure] = {}
    active: dict[tuple[str, str], tuple[int, datetime, int]] = {}  # key -> (level, start, start_tcb_id)
    previous_time: datetime | None = None

    for snapshot in ordered:
        now = snapshot.issued_at
        long_gap = previous_time is not None and now - previous_time > timedelta(hours=LONG_GAP_HOURS)

        for key, (level, start, start_tcb_id) in list(active.items()):
            if long_gap:
                areas[key].has_long_gap = True
            listed = snapshot.areas.get(key)
            if snapshot.is_final or listed is None or listed[0] != level:
                if now > start:
                    areas[key].intervals.append(Interval(level, start, now, start_tcb_id, snapshot.tcb_id))
                    areas[key].end = max(areas[key].end, now)
                del active[key]

        for key, (level, island_group) in snapshot.areas.items():
            if level not in SIGNAL_LEVELS:
                logger.warning("TCB %s: ignoring out-of-range signal level %s for %s", snapshot.tcb_id, level, key)
                continue
            area = areas.get(key)
            if area is None:
                area = areas[key] = AreaExposure(
                    province=key[0], municipality=key[1], island_group=island_group,
                    max_signal_level=level, start=now, end=now,
                )
            if level > area.max_signal_level:
                area.max_signal_level = level
                area.island_group = island_group
            area.end = max(area.end, now)
            if key not in active and not snapshot.is_final:
                active[key] = (level, now, snapshot.tcb_id)

        previous_time = now

    if active:
        last = ordered[-1]
        for key, (level, start, start_tcb_id) in active.items():
            if last.issued_at > start:
                areas[key].intervals.append(Interval(level, start, last.issued_at, start_tcb_id, last.tcb_id))
            areas[key].has_open_interval = True

    return areas


def serialize_summary(summary: AreaExposureSummary) -> dict:
    """The one response shape both exposure tables (Main Dashboard Exposure
    Summary, Assessment & Reporting Areas Affected) read."""
    hours = [float(getattr(summary, f"signal_{level}_hours") or 0) for level in SIGNAL_LEVELS]
    return {
        "summary_id": summary.summary_id,
        "boundary_id": summary.boundary_id,
        "province": summary.province,
        "municipality": summary.municipality,
        "island_group": summary.island_group,
        "max_signal_level": summary.max_signal_level,
        "signal_1_hours": hours[0],
        "signal_2_hours": hours[1],
        "signal_3_hours": hours[2],
        "signal_4_hours": hours[3],
        "signal_5_hours": hours[4],
        "total_exposure_hours": float(summary.total_exposure_hours),
        "payout_hours": float(summary.payout_hours) if summary.payout_hours is not None else None,
        "start_time": summary.start_time,
        "end_time": summary.end_time,
        "is_eligible_6hr": summary.is_eligible_6hr,
        "has_open_interval": summary.has_open_interval,
        "has_long_gap": summary.has_long_gap,
    }


class ExposureCalculatorService:
    """
    Aggregates a typhoon's successive PAGASA bulletins into per-municipality
    exposure summaries (tbl_area_exposure_summary) and the intervals behind
    them (tbl_exposure_intervals).

    This deliberately does not model a circular "signal radius" geometry:
    PAGASA publishes TCWS areas as named municipality/province lists per
    bulletin (resolved into tbl_tcb_signals by bulletin_parser.py), not as a
    radius around the storm center. Exposure is therefore a time-series
    reconstruction over named areas -- see build_area_exposures and
    METHODOLOGY_NOTE for the exact interval rules.

    This is the only place exposure hours are calculated; the API, the
    assessment run and both frontend tables all read its results.
    """

    @classmethod
    def compute_for_typhoon(cls, typhoon_id: int, db: Session) -> list[AreaExposureSummary]:
        bulletins = (
            db.query(TropicalCycloneBulletin)
            .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
            .order_by(TropicalCycloneBulletin.issued_at.asc(), TropicalCycloneBulletin.bulletin_count.asc())
            .all()
        )
        # A bulletin whose "Issued at" couldn't be read carries its ingestion
        # time instead, which would invent a duration -- left out entirely.
        usable = [b for b in bulletins if b.issued_at_parsed is not False]
        if len(usable) < len(bulletins):
            logger.warning(
                "Typhoon %s: %d bulletin(s) without a parsed issue time left out of exposure",
                typhoon_id, len(bulletins) - len(usable),
            )

        # Keyed on (province, municipality), not municipality alone --
        # nationwide, the same municipality name exists in several provinces
        # (e.g. "Santa Cruz"). Relies on TcbSignal.province (see
        # backend/migrations/2026-08-20_tcb_signal_province.sql). The lowest
        # boundary_id per municipality stands for it, so the choice is stable
        # across recomputes. load_only: ~42k barangay rows, geometry not needed.
        boundaries: dict[tuple[str, str], AdminBoundary] = {}
        for b in (
            db.query(AdminBoundary)
            .options(load_only(AdminBoundary.boundary_id, AdminBoundary.province, AdminBoundary.municipality))
            .order_by(AdminBoundary.boundary_id.asc())
            .all()
        ):
            boundaries.setdefault((b.province.lower(), b.municipality.lower()), b)

        signals_by_tcb: dict[int, list[TcbSignal]] = {}
        if usable:
            for signal in db.query(TcbSignal).filter(TcbSignal.tcb_id.in_([b.tcb_id for b in usable])).all():
                signals_by_tcb.setdefault(signal.tcb_id, []).append(signal)

        snapshots = []
        for bulletin in usable:
            areas: dict[tuple[str, str], tuple[int, int]] = {}
            for signal in signals_by_tcb.get(bulletin.tcb_id, []):
                if not signal.province:
                    # Signal predates the province column (pre-2026-08-20) --
                    # can't disambiguate safely, skip rather than guess.
                    continue
                key = (signal.province.lower(), signal.area_name.lower())
                if key not in boundaries:
                    continue
                # An LGU is seeded once per bulletin at its highest signal,
                # but keep the max defensively.
                if key not in areas or signal.signal_level > areas[key][0]:
                    areas[key] = (signal.signal_level, signal.island_group)
            snapshots.append(BulletinSnapshot(
                tcb_id=bulletin.tcb_id,
                bulletin_count=bulletin.bulletin_count,
                issued_at=bulletin.issued_at,
                is_final=bool(bulletin.is_final),
                areas=areas,
            ))

        exposures = build_area_exposures(snapshots)

        stored: dict[tuple[str, str], list[AreaExposureSummary]] = {}
        for s in sorted(
            db.query(AreaExposureSummary).filter(AreaExposureSummary.typhoon_id == typhoon_id).all(),
            key=lambda s: s.summary_id,
        ):
            stored.setdefault((s.province.lower(), s.municipality.lower()), []).append(s)
        existing, duplicates, blocked = cls._pick_one_per_area(stored, db)
        if duplicates:
            cls._retire_stale_summaries(duplicates, db)
            db.flush()

        summaries = []
        for key, exposure in exposures.items():
            boundary = boundaries[key]
            hours = exposure.hours_by_level()
            payout_hours = hours[exposure.max_signal_level]
            summary = existing.pop(key, None)
            if summary is None:
                summary = AreaExposureSummary(
                    typhoon_id=typhoon_id,
                    province=boundary.province,
                    municipality=boundary.municipality,
                )
                db.add(summary)
            elif key not in blocked:
                # Stored under another casing (e.g. 'CAGAYAN / PAMPLONA' from a
                # CSV-created boundary) -- take the boundary's own spelling.
                summary.province = boundary.province
                summary.municipality = boundary.municipality
            summary.boundary_id = boundary.boundary_id
            summary.island_group = exposure.island_group
            summary.max_signal_level = exposure.max_signal_level
            summary.start_time = exposure.start
            summary.end_time = exposure.end
            for level in SIGNAL_LEVELS:
                setattr(summary, f"signal_{level}_hours", hours[level])
            summary.total_exposure_hours = sum(hours.values(), Decimal("0"))
            summary.payout_hours = payout_hours
            summary.is_eligible_6hr = payout_hours >= 6
            summary.has_open_interval = exposure.has_open_interval
            summary.has_long_gap = exposure.has_long_gap
            summaries.append(summary)

        cls._retire_stale_summaries(list(existing.values()), db)

        db.query(ExposureInterval).filter(ExposureInterval.typhoon_id == typhoon_id).delete(synchronize_session=False)
        for key, exposure in exposures.items():
            boundary = boundaries[key]
            for interval in exposure.intervals:
                db.add(ExposureInterval(
                    typhoon_id=typhoon_id,
                    province=boundary.province,
                    municipality=boundary.municipality,
                    signal_level=interval.signal_level,
                    start_time=interval.start,
                    end_time=interval.end,
                    start_tcb_id=interval.start_tcb_id,
                    end_tcb_id=interval.end_tcb_id,
                ))

        db.commit()
        for summary in summaries:
            db.refresh(summary)

        return summaries

    @staticmethod
    def _referenced_summary_ids(summary_ids: list[int], db: Session) -> set[int]:
        return {
            summary_id
            for (summary_id,) in db.query(RiskAssessment.summary_id)
            .filter(RiskAssessment.summary_id.in_(summary_ids))
            .distinct()
            .all()
        }

    @classmethod
    def _pick_one_per_area(
        cls, stored: dict[tuple[str, str], list[AreaExposureSummary]], db: Session,
    ) -> tuple[dict[tuple[str, str], AreaExposureSummary], list[AreaExposureSummary], set[tuple[str, str]]]:
        """
        One summary per (province, municipality), compared case-insensitively.
        Before 2026-10-22 a CSV import could create boundaries spelled
        'CAGAYAN / PAMPLONA' next to the seeded 'Cagayan / Pamplona', and the
        old calculator stored a second summary for them that later recomputes
        never touched. Keeps the row an assessment points at (else the oldest)
        and returns the rest as duplicates for _retire_stale_summaries. Keys
        where a duplicate is itself referenced (so it is zeroed, not deleted)
        come back in `blocked`: renaming the kept row there could collide.
        """
        dup_ids = [s.summary_id for rows in stored.values() if len(rows) > 1 for s in rows]
        referenced = cls._referenced_summary_ids(dup_ids, db) if dup_ids else set()
        existing: dict[tuple[str, str], AreaExposureSummary] = {}
        duplicates: list[AreaExposureSummary] = []
        blocked: set[tuple[str, str]] = set()
        for key, rows in stored.items():
            keep = next((r for r in rows if r.summary_id in referenced), rows[0])
            existing[key] = keep
            for row in rows:
                if row is not keep:
                    duplicates.append(row)
                    if row.summary_id in referenced:
                        blocked.add(key)
        if duplicates:
            logger.warning(
                "Retiring %d exposure summaries that duplicate another row's area in a different casing",
                len(duplicates),
            )
        return existing, duplicates, blocked

    @staticmethod
    def _retire_stale_summaries(stale: list[AreaExposureSummary], db: Session) -> None:
        """
        Municipalities no longer under any signal (e.g. a corrected bulletin
        dropped them). Rows no assessment points at are deleted; rows a
        RiskAssessment still references (tbl_risk_assessment.summary_id has no
        FK) are zeroed instead, so that assessment keeps its context while no
        longer counting as exposed.
        """
        if not stale:
            return
        referenced = ExposureCalculatorService._referenced_summary_ids([s.summary_id for s in stale], db)
        for summary in stale:
            if summary.summary_id in referenced:
                logger.warning(
                    "Exposure summary %s (%s, %s) no longer under any signal but referenced by an assessment; zeroed",
                    summary.summary_id, summary.province, summary.municipality,
                )
                for level in SIGNAL_LEVELS:
                    setattr(summary, f"signal_{level}_hours", Decimal("0"))
                summary.total_exposure_hours = Decimal("0")
                summary.payout_hours = Decimal("0")
                summary.is_eligible_6hr = False
                summary.has_open_interval = False
                summary.has_long_gap = False
            else:
                db.delete(summary)
