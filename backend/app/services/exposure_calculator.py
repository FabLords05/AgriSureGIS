from sqlalchemy.orm import Session

from app.models.models import (
    AdminBoundary,
    AreaExposureSummary,
    TcbSignal,
    TropicalCycloneBulletin,
)


class ExposureCalculatorService:
    """
    Aggregates a typhoon's successive PAGASA bulletins into per-boundary exposure
    summaries in tbl_area_exposure_summary.

    This deliberately does not model a circular "signal radius" geometry: PAGASA
    publishes TCWS signal areas as named municipality/province lists per bulletin
    (captured in tbl_tcb_signals by Sprint 2's scraper), not as a radius around the
    storm center. So exposure duration is a time-series aggregation over named
    areas — matching how many bulletins in a row list a boundary as under signal —
    rather than a spatial buffer/intersection calculation.
    """

    @classmethod
    def compute_for_typhoon(cls, typhoon_id: int, db: Session) -> list[AreaExposureSummary]:
        bulletins = (
            db.query(TropicalCycloneBulletin)
            .filter(TropicalCycloneBulletin.typhoon_id == typhoon_id)
            .order_by(TropicalCycloneBulletin.issued_at.asc())
            .all()
        )
        if not bulletins:
            return []

        # Keyed on (province, municipality), not municipality alone -- at
        # Region X + Caraga scale (8 provinces) municipality names never
        # collided, but nationwide (81 provinces) duplicate municipality
        # names across different provinces are common (e.g. multiple "Santa
        # Cruz"), so municipality-only keying could silently attribute
        # exposure to the wrong province's boundary. Relies on
        # TcbSignal.province, populated by bulletin_parser.py's matching --
        # see backend/migrations/2026-08-20_tcb_signal_province.sql.
        boundaries_by_province_municipality = {
            (b.province.lower(), b.municipality.lower()): b
            for b in db.query(AdminBoundary).all()
        }

        # boundary_id -> {"boundary": AdminBoundary, "start": dt, "end": dt, "max_signal_level": int}
        timelines: dict[int, dict] = {}

        for bulletin in bulletins:
            signals = db.query(TcbSignal).filter(TcbSignal.tcb_id == bulletin.tcb_id).all()
            for signal in signals:
                if not signal.province:
                    # Signal predates the province column (pre-2026-08-20) --
                    # can't disambiguate safely, skip rather than risk a
                    # wrong-province match.
                    continue
                boundary = boundaries_by_province_municipality.get(
                    (signal.province.lower(), signal.area_name.lower())
                )
                if boundary is None:
                    continue

                entry = timelines.get(boundary.boundary_id)
                if entry is None:
                    timelines[boundary.boundary_id] = {
                        "boundary": boundary,
                        "start": bulletin.issued_at,
                        "end": bulletin.issued_at,
                        "max_signal_level": signal.signal_level,
                    }
                else:
                    entry["end"] = bulletin.issued_at
                    entry["max_signal_level"] = max(entry["max_signal_level"], signal.signal_level)

        summaries = []
        for boundary_id, entry in timelines.items():
            total_hours = (entry["end"] - entry["start"]).total_seconds() / 3600

            summary = (
                db.query(AreaExposureSummary)
                .filter(
                    AreaExposureSummary.typhoon_id == typhoon_id,
                    AreaExposureSummary.boundary_id == boundary_id,
                )
                .first()
            )
            if summary is None:
                summary = AreaExposureSummary(
                    typhoon_id=typhoon_id,
                    boundary_id=boundary_id,
                    province=entry["boundary"].province,
                    municipality=entry["boundary"].municipality,
                    max_signal_level=entry["max_signal_level"],
                    start_time=entry["start"],
                    end_time=entry["end"],
                    is_eligible_6hr=total_hours >= 6,
                    total_exposure_hours=round(total_hours, 2),
                )
                db.add(summary)
            else:
                summary.max_signal_level = entry["max_signal_level"]
                summary.start_time = entry["start"]
                summary.end_time = entry["end"]
                summary.is_eligible_6hr = total_hours >= 6
                summary.total_exposure_hours = round(total_hours, 2)

            summaries.append(summary)

        db.commit()
        for summary in summaries:
            db.refresh(summary)

        return summaries
