"""
Archive & Clear (2026-10-22).

PCIC re-exports CSV/GPKG from PABS for every typhoon, so the live DB's
uploaded records only matter until that typhoon's assessment is done. Once
EVERY typhoon the live data was assessed/checked against is at least
CLEAR_AFTER_DAYS past its last bulletin, a user (Admin or GIS Specialist) may
clear it. Before anything is deleted, every uploaded record and polygon is
copied into the separate, read-only archive database (backend/archive_schema.sql),
and a full pg_dump goes to BACKUP_DIR + Google Drive.

archive_and_clear() order -- anything failing before the final commit leaves
the live DB untouched:
  1. re-check eligibility (never trust the button state)
  2. safety pg_dump (backup_service.run_backup, kind='archive')
  3. inside ONE archive-DB transaction: copy every table, verify each copied
     count against what was read, then run the live DELETEs in the live
     session (not yet committed)
  4. commit the archive, then commit the live deletes
If the live commit itself fails after the archive committed, the archive
holds a copy of data that is still live; a retry archives it again. That is
harmless (archives are read-only snapshots), and logged loudly.

Typhoons, bulletins, signals and exposure summaries are copied for context
(the archive map draws them) but stay live: later typhoons and the
Monitoring screen still use them. Users, the activity log and the PCIC
matrices are never touched.

Rows are moved with raw SQL rather than ORM models: geometry columns come
back from psycopg2 as hex EWKB strings, which PostGIS accepts as-is on
insert, so polygons copy byte-for-byte without a shapely round trip.
"""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import column, table, text
from sqlalchemy.orm import Session

from app.core.database import archive_reader_engine, archive_writer_engine
from app.core.farms_cache import invalidate_farms_cache
from app.core.farms_view import refresh_farm_latest_insurance_view
from app.models.models import SystemUser
from app.services.backup_service import run_backup

logger = logging.getLogger("agrisuregis.archive")

CLEAR_AFTER_DAYS = 7
CONFIRM_WORD = "CLEAR"
_COPY_CHUNK = 1000

# Only one Archive & Clear at a time -- a second click while the first is
# still copying would otherwise archive the same rows twice.
_archive_lock = threading.Lock()


class ArchiveError(RuntimeError):
    pass


class ArchiveBusyError(ArchiveError):
    pass


# (live table, archive table, columns, JSONB columns, WHERE clause)
# WHERE clauses may use :typhoon_ids. The first group is deleted from live
# afterwards; the second (typhoon context) is copied only.
_PABS_TABLES = [
    ("tbl_farmers_profile", "arc_farmers",
     ["farmer_id", "farmers_id", "rsbsa_no", "last_name", "first_name", "middle_name", "created_at", "updated_at"],
     [], None),
    ("tbl_farms", "arc_farms",
     ["farm_id", "farmer_id", "boundary_id", "csv_farm_reference", "georef_id", "province", "municipality",
      "barangay", "area_size", "location_geom", "created_at", "updated_at"],
     [], None),
    ("tbl_insurance_records", "arc_insurance_records",
     ["insurance_records_id", "farmer_id", "farm_id", "policy_no", "program_type", "product_name",
      "effectivity_date", "expiry_date", "amount_cover", "created_at", "updated_at", "is_used",
      "used_for_typhoon_id", "used_at"],
     [], None),
    ("tbl_risk_assessment", "arc_risk_assessment",
     ["assessment_id", "insurance_records_id", "summary_id", "matrix_id", "indemnity_matrix_id", "crop_stage_no",
      "crop_stage", "stage_group", "period_of_exposure", "wind_velocity", "indemnity_factor", "estimated_damage",
      "final_indemnity_payment", "assessment_date", "user_id"],
     [], None),
    ("tbl_insurance_usage", "arc_insurance_usage",
     ["usage_id", "insurance_records_id", "typhoon_id", "assessment_id", "is_used", "marked_at", "finalized_at"],
     [], None),
    ("tbl_planted_verification", "arc_planted_verification",
     ["verification_id", "farm_id", "typhoon_id", "is_planted", "verified_by", "verified_at", "notes"],
     [], None),
    ("tbl_sar_planted_check", "arc_sar_planted_check",
     ["check_id", "farm_id", "typhoon_id", "status", "reason_code", "t0_date", "tp_date", "vh_rise_db",
      "ratio_drop_db", "relative_orbit", "scene_count", "window_start", "window_end", "checked_by", "checked_at"],
     [], None),
    ("tbl_sar_observation", "arc_sar_observation",
     ["observation_id", "farm_id", "scene_date", "relative_orbit", "vv_db", "vh_db", "fetched_at"],
     [], None),
]

_CONTEXT_TABLES = [
    ("tbl_typhoons", "arc_typhoons",
     ["typhoon_id", "name", "year", "is_active"],
     [], "typhoon_id = ANY(:typhoon_ids)"),
    ("tbl_tropical_cyclone_bulletins", "arc_tropical_cyclone_bulletins",
     ["tcb_id", "typhoon_id", "title", "bulletin_count", "category", "max_sustained_winds", "gustiness",
      "issued_at", "expires_at", "center_geom", "max_signal_level", "tcws_areas", "is_final",
      "wind_radius_km", "storm_force_radius_km", "forecast_track"],
     ["tcws_areas", "forecast_track"], "typhoon_id = ANY(:typhoon_ids)"),
    ("tbl_tcb_signals", "arc_tcb_signals",
     ["signal_id", "tcb_id", "signal_level", "island_group", "area_name", "province"],
     [], "tcb_id IN (SELECT tcb_id FROM tbl_tropical_cyclone_bulletins WHERE typhoon_id = ANY(:typhoon_ids))"),
    ("tbl_area_exposure_summary", "arc_area_exposure_summary",
     ["summary_id", "typhoon_id", "boundary_id", "province", "municipality", "max_signal_level", "start_time",
      "end_time", "is_eligible_6hr", "total_exposure_hours", "computed_at"],
     [], "typhoon_id = ANY(:typhoon_ids)"),
    ("tbl_admin_boundaries", "arc_admin_boundaries",
     ["boundary_id", "psgc_code", "province", "municipality", "barangay", "boundary_geom"],
     [], "boundary_id IN (SELECT boundary_id FROM tbl_farms WHERE boundary_id IS NOT NULL "
         "UNION SELECT boundary_id FROM tbl_area_exposure_summary "
         "WHERE typhoon_id = ANY(:typhoon_ids) AND boundary_id IS NOT NULL)"),
]

# FK-safe: children before parents. tbl_sar_fetch_coverage is SAR cache
# bookkeeping (not archived) but still references tbl_farms.
_LIVE_DELETE_ORDER = [
    "tbl_sar_planted_check",
    "tbl_planted_verification",
    "tbl_sar_observation",
    "tbl_sar_fetch_coverage",
    "tbl_insurance_usage",
    "tbl_risk_assessment",
    "tbl_insurance_records",
    "tbl_farms",
    "tbl_farmers_profile",
]

# Every typhoon the live data was assessed, locked, or SAR-checked against.
_LIVE_TYPHOONS_SQL = """
    SELECT s.typhoon_id FROM tbl_risk_assessment ra
    JOIN tbl_area_exposure_summary s ON s.summary_id = ra.summary_id
    WHERE ra.matrix_id IS NOT NULL AND s.typhoon_id IS NOT NULL
    UNION SELECT typhoon_id FROM tbl_insurance_usage
    UNION SELECT typhoon_id FROM tbl_sar_planted_check
    UNION SELECT typhoon_id FROM tbl_planted_verification
"""


# ─── Eligibility ─────────────────────────────────────────────────────────────

def _live_counts(db: Session) -> dict:
    return {
        "farmers": db.execute(text("SELECT count(*) FROM tbl_farmers_profile")).scalar_one(),
        "farms": db.execute(text("SELECT count(*) FROM tbl_farms")).scalar_one(),
        "policies": db.execute(text("SELECT count(*) FROM tbl_insurance_records")).scalar_one(),
        "assessments": db.execute(
            text("SELECT count(*) FROM tbl_risk_assessment WHERE matrix_id IS NOT NULL")
        ).scalar_one(),
    }


def _live_typhoons(db: Session) -> list[dict]:
    rows = db.execute(text(f"""
        SELECT t.typhoon_id, t.name, t.year, max(b.issued_at) AS last_bulletin_at
        FROM tbl_typhoons t
        LEFT JOIN tbl_tropical_cyclone_bulletins b ON b.typhoon_id = t.typhoon_id
        WHERE t.typhoon_id IN ({_LIVE_TYPHOONS_SQL})
        GROUP BY t.typhoon_id, t.name, t.year
        ORDER BY last_bulletin_at NULLS LAST, t.typhoon_id
    """)).all()
    return [
        {
            "typhoon_id": r.typhoon_id,
            "name": r.name,
            "year": r.year,
            "last_bulletin_at": r.last_bulletin_at,
            "clear_after": r.last_bulletin_at + timedelta(days=CLEAR_AFTER_DAYS) if r.last_bulletin_at else None,
        }
        for r in rows
    ]


def eligibility(db: Session, now: datetime | None = None) -> dict:
    """Whether Archive & Clear may run now, and if not, why and from when.
    Requires live data AND at least one typhoon assessed against it (the
    feature exists to close out a typhoon -- fresh, never-assessed uploads
    are not clearable). A typhoon with no bulletins on record imposes no
    waiting period."""
    now = now or datetime.now(timezone.utc)
    counts = _live_counts(db)
    typhoons = _live_typhoons(db)

    clear_afters = [t["clear_after"] for t in typhoons if t["clear_after"] is not None]
    eligible_at = max(clear_afters) if clear_afters else None

    if counts["farms"] == 0 and counts["farmers"] == 0 and counts["policies"] == 0:
        eligible, reason = False, "There are no uploaded records to archive."
    elif not typhoons:
        eligible, reason = False, "No typhoon has been assessed against the current records yet."
    elif eligible_at is not None and now < eligible_at:
        eligible = False
        reason = f"Allowed {CLEAR_AFTER_DAYS} days after the last bulletin of every assessed typhoon."
    else:
        eligible, reason = True, None

    return {
        "eligible": eligible,
        "reason": reason,
        "eligible_at": eligible_at,
        "clear_after_days": CLEAR_AFTER_DAYS,
        "counts": counts,
        "typhoons": typhoons,
        "label": _label(typhoons),
    }


def _label(typhoons: list[dict]) -> str:
    return ", ".join(f"{t['name']} {t['year']}" for t in typhoons) or "No typhoon"


# ─── Archive & Clear ─────────────────────────────────────────────────────────

def _copy_table(db: Session, conn, archive_id: int, spec, params: dict) -> int:
    live, arc, cols, json_cols, where = spec
    sql = f"SELECT {', '.join(cols)} FROM {live}" + (f" WHERE {where}" if where else "")
    target = table(arc, column("archive_id"), *(column(c) for c in cols))
    result = db.execute(text(sql).execution_options(stream_results=True), params)
    copied = 0
    while True:
        chunk = result.fetchmany(_COPY_CHUNK)
        if not chunk:
            break
        rows = []
        for r in chunk:
            row = dict(r._mapping)
            for jc in json_cols:
                if row[jc] is not None:
                    row[jc] = json.dumps(row[jc])
            row["archive_id"] = archive_id
            rows.append(row)
        conn.execute(target.insert(), rows)
        copied += len(rows)
    return copied


def archive_and_clear(db: Session, user: SystemUser) -> dict:
    if not _archive_lock.acquire(blocking=False):
        raise ArchiveBusyError("An Archive & Clear is already running. Wait for it to finish.")
    try:
        return _archive_and_clear(db, user)
    finally:
        _archive_lock.release()


def _archive_and_clear(db: Session, user: SystemUser) -> dict:
    state = eligibility(db)
    if not state["eligible"]:
        raise ArchiveError(state["reason"])

    writer = archive_writer_engine()  # raises ArchiveNotConfiguredError before any dump is taken
    backup = run_backup(db, "archive", user.user_id)

    typhoon_ids = [t["typhoon_id"] for t in state["typhoons"]]
    params = {"typhoon_ids": typhoon_ids}
    typhoons_json = [
        {**t, "last_bulletin_at": t["last_bulletin_at"].isoformat() if t["last_bulletin_at"] else None,
         "clear_after": t["clear_after"].isoformat() if t["clear_after"] else None}
        for t in state["typhoons"]
    ]
    archived_by = f"{user.firstname} {user.lastname}".strip()
    specs = _PABS_TABLES + _CONTEXT_TABLES

    try:
        # One REPEATABLE READ snapshot for the count, the copy AND the delete:
        # a CSV upload landing mid-archive is invisible to all three, so its
        # rows are neither archived nor deleted -- they simply stay live.
        # (run_backup committed the session, so this starts a fresh transaction.)
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        # tbl_archive_batch rejects UPDATE (read-only trigger), so its counts
        # are taken up front and the copy is then verified against them.
        row_counts = {
            spec[1]: db.execute(
                text(f"SELECT count(*) FROM {spec[0]}" + (f" WHERE {spec[4]}" if spec[4] else "")), params
            ).scalar_one()
            for spec in specs
        }
        pabs_total = sum(row_counts[spec[1]] for spec in _PABS_TABLES)

        with writer.begin() as conn:
            archive_id = conn.execute(
                text("""
                    INSERT INTO tbl_archive_batch
                        (label, typhoons, archived_by_user_id, archived_by_name, row_counts, record_count,
                         dump_file_name, gdrive_file_id)
                    VALUES (:label, CAST(:typhoons AS JSONB), :uid, :uname, CAST(:counts AS JSONB), :total,
                            :dump, :gdrive)
                    RETURNING archive_id
                """),
                {"label": state["label"], "typhoons": json.dumps(typhoons_json), "uid": user.user_id,
                 "uname": archived_by, "counts": json.dumps(row_counts), "total": pabs_total,
                 "dump": backup.file_name, "gdrive": backup.gdrive_file_id},
            ).scalar_one()

            for spec in specs:
                copied = _copy_table(db, conn, archive_id, spec, params)
                written = conn.execute(
                    text(f"SELECT count(*) FROM {spec[1]} WHERE archive_id = :aid"), {"aid": archive_id}
                ).scalar_one()
                if not (copied == written == row_counts[spec[1]]):
                    raise ArchiveError(
                        f"Archive copy check failed for {spec[1]}: expected {row_counts[spec[1]]}, "
                        f"read {copied}, wrote {written}. Nothing was deleted."
                    )

            for live in _LIVE_DELETE_ORDER:
                db.execute(text(f"DELETE FROM {live}"))
        # Archive committed here (end of `with`); live deletes still pending.
    except Exception:
        db.rollback()
        raise

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Archive %s committed but the live delete failed -- live data is untouched; "
            "a retry will archive it again.", archive_id,
        )
        raise ArchiveError("The archive was saved, but clearing the live records failed. Nothing was deleted.")

    refresh_farm_latest_insurance_view(db)
    invalidate_farms_cache()

    return {
        "archive_id": archive_id,
        "label": state["label"],
        "row_counts": row_counts,
        "record_count": pabs_total,
        "dump_file_name": backup.file_name,
        "gdrive_uploaded": backup.gdrive_file_id is not None,
        "gdrive_error": backup.gdrive_error,
    }


# ─── Read-only viewing (archive READER login only) ──────────────────────────

def list_archives() -> list[dict]:
    with archive_reader_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT archive_id, label, typhoons, archived_at, archived_by_name, row_counts, record_count,
                   dump_file_name, gdrive_file_id
            FROM tbl_archive_batch ORDER BY archived_at DESC
        """)).mappings().all()
    return [dict(r) for r in rows]


def get_archive(archive_id: int) -> dict | None:
    with archive_reader_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM tbl_archive_batch WHERE archive_id = :aid"), {"aid": archive_id}
        ).mappings().first()
    return dict(row) if row else None


# One row per archived policy x computed assessment (a policy assessed for two
# typhoons shows twice; one never assessed shows once with a blank payout).
_RECORDS_FROM = """
    FROM arc_insurance_records ir
    LEFT JOIN arc_farms f ON f.archive_id = ir.archive_id AND f.farm_id = ir.farm_id
    LEFT JOIN arc_farmers fp ON fp.archive_id = ir.archive_id AND fp.farmer_id = ir.farmer_id
    LEFT JOIN arc_risk_assessment ra
        ON ra.archive_id = ir.archive_id AND ra.insurance_records_id = ir.insurance_records_id
       AND ra.matrix_id IS NOT NULL
    LEFT JOIN arc_area_exposure_summary s ON s.archive_id = ra.archive_id AND s.summary_id = ra.summary_id
    LEFT JOIN arc_typhoons t ON t.archive_id = s.archive_id AND t.typhoon_id = s.typhoon_id
    WHERE ir.archive_id = :aid
      AND (CAST(:q AS TEXT) = '' OR concat_ws(' ', fp.first_name, fp.middle_name, fp.last_name, fp.farmers_id,
                                ir.policy_no, f.municipality, f.barangay, f.csv_farm_reference) ILIKE :like)
"""

_RECORDS_SELECT = """
    SELECT ir.insurance_records_id, f.farm_id, fp.farmers_id,
           concat_ws(' ', fp.first_name, fp.middle_name, fp.last_name) AS farmer_name,
           f.csv_farm_reference AS farm_reference, f.province, f.municipality, f.barangay, f.area_size,
           ir.policy_no, ir.program_type, ir.effectivity_date, ir.expiry_date, ir.amount_cover,
           t.name AS typhoon_name, t.year AS typhoon_year, s.max_signal_level AS wind_signal,
           ra.crop_stage, ra.period_of_exposure, ra.wind_velocity, ra.indemnity_factor,
           ra.estimated_damage, ra.final_indemnity_payment, ra.assessment_date
"""


def archive_records(archive_id: int, q: str = "", page: int = 1, page_size: int = 50) -> dict:
    q = (q or "").strip()
    page = max(page, 1)
    params = {"aid": archive_id, "q": q, "like": f"%{q}%", "limit": page_size, "offset": (page - 1) * page_size}
    with archive_reader_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) {_RECORDS_FROM}"), params).scalar_one()
        rows = conn.execute(
            text(f"{_RECORDS_SELECT} {_RECORDS_FROM} ORDER BY farmer_name, ir.policy_no, t.year, t.name "
                 "LIMIT :limit OFFSET :offset"),
            params,
        ).mappings().all()
    return {"total": total, "page": page, "page_size": page_size, "rows": [dict(r) for r in rows]}


def archive_records_all(archive_id: int):
    """Every row of archive_records(), unpaged -- for the CSV export."""
    params = {"aid": archive_id, "q": "", "like": "%"}
    with archive_reader_engine().connect() as conn:
        result = conn.execute(
            text(f"{_RECORDS_SELECT} {_RECORDS_FROM} ORDER BY farmer_name, ir.policy_no, t.year, t.name"), params
        ).mappings()
        for r in result:
            yield dict(r)


def archived_typhoons() -> list[dict]:
    """Every typhoon held in some archive, with the newest archive holding it.
    Typhoon ids are stable -- typhoons stay live through Archive & Clear -- so
    Assessment & Reporting can match these against its live typhoon list."""
    with archive_reader_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (t.typhoon_id) t.typhoon_id, t.name, t.year,
                   b.archive_id, b.label, b.archived_at
            FROM arc_typhoons t
            JOIN tbl_archive_batch b ON b.archive_id = t.archive_id
            ORDER BY t.typhoon_id, b.archived_at DESC
        """)).mappings().all()
    return [dict(r) for r in rows]


def archived_typhoon_assessments(typhoon_id: int) -> dict | None:
    """One typhoon's computed assessments from the newest archive holding it,
    joined to their farm/farmer/policy/boundary -- the raw material for the
    PABS-shaped rows app/api/archives.py builds. None if never archived."""
    with archive_reader_engine().connect() as conn:
        batch = conn.execute(text("""
            SELECT b.archive_id, b.label, b.archived_at
            FROM arc_typhoons t JOIN tbl_archive_batch b ON b.archive_id = t.archive_id
            WHERE t.typhoon_id = :tid
            ORDER BY b.archived_at DESC LIMIT 1
        """), {"tid": typhoon_id}).mappings().first()
        if batch is None:
            return None
        params = {"aid": batch["archive_id"], "tid": typhoon_id}
        rows = conn.execute(text("""
            SELECT ra.assessment_id, ra.insurance_records_id, ra.matrix_id, ra.period_of_exposure,
                   ra.wind_velocity, ra.crop_stage, ra.final_indemnity_payment, ra.assessment_date,
                   s.typhoon_id, t.name AS typhoon_name,
                   ir.policy_no, ir.amount_cover,
                   f.csv_farm_reference, f.area_size,
                   COALESCE(bd.province, f.province) AS province,
                   COALESCE(bd.municipality, f.municipality) AS municipality,
                   COALESCE(bd.barangay, f.barangay) AS barangay,
                   fp.farmers_id, fp.last_name, fp.first_name, fp.middle_name
            FROM arc_risk_assessment ra
            JOIN arc_area_exposure_summary s ON s.archive_id = ra.archive_id AND s.summary_id = ra.summary_id
            LEFT JOIN arc_typhoons t ON t.archive_id = s.archive_id AND t.typhoon_id = s.typhoon_id
            LEFT JOIN arc_insurance_records ir
                   ON ir.archive_id = ra.archive_id AND ir.insurance_records_id = ra.insurance_records_id
            LEFT JOIN arc_farms f ON f.archive_id = ir.archive_id AND f.farm_id = ir.farm_id
            LEFT JOIN arc_admin_boundaries bd ON bd.archive_id = f.archive_id AND bd.boundary_id = f.boundary_id
            LEFT JOIN arc_farmers fp ON fp.archive_id = ir.archive_id AND fp.farmer_id = ir.farmer_id
            WHERE ra.archive_id = :aid AND s.typhoon_id = :tid AND ra.matrix_id IS NOT NULL
            ORDER BY ra.assessment_date DESC
        """), params).mappings().all()
        max_winds = conn.execute(text("""
            SELECT max(max_sustained_winds) FROM arc_tropical_cyclone_bulletins
            WHERE archive_id = :aid AND typhoon_id = :tid
        """), params).scalar()
    return {**dict(batch), "max_winds": max_winds, "rows": [dict(r) for r in rows]}


# Browsers stall drawing tens of thousands of polygons; the viewer asks per
# map viewport (bbox), like the live Spatial Analysis map.
MAX_MAP_FARMS = 5000


def archive_farms_geojson(archive_id: int, bbox: tuple[float, float, float, float] | None) -> dict:
    where = "f.archive_id = :aid AND f.location_geom IS NOT NULL"
    params: dict = {"aid": archive_id, "limit": MAX_MAP_FARMS + 1}
    if bbox:
        where += " AND f.location_geom && ST_MakeEnvelope(:w, :s, :e, :n, 4326)"
        params.update(w=bbox[0], s=bbox[1], e=bbox[2], n=bbox[3])
    with archive_reader_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT f.farm_id, f.municipality, f.barangay, f.area_size, f.csv_farm_reference,
                   concat_ws(' ', fp.first_name, fp.last_name) AS farmer_name,
                   COALESCE((SELECT sum(ra.final_indemnity_payment)
                             FROM arc_insurance_records ir
                             JOIN arc_risk_assessment ra ON ra.archive_id = ir.archive_id
                                  AND ra.insurance_records_id = ir.insurance_records_id AND ra.matrix_id IS NOT NULL
                             WHERE ir.archive_id = f.archive_id AND ir.farm_id = f.farm_id), 0) AS total_payout,
                   ST_AsGeoJSON(f.location_geom, 6) AS geometry
            FROM arc_farms f
            LEFT JOIN arc_farmers fp ON fp.archive_id = f.archive_id AND fp.farmer_id = f.farmer_id
            WHERE {where}
            LIMIT :limit
        """), params).mappings().all()
        extent = conn.execute(
            text("SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
                 "(SELECT ST_Extent(location_geom) AS e FROM arc_farms WHERE archive_id = :aid) x"),
            {"aid": archive_id},
        ).first()

    numeric = ("area_size", "total_payout")
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(r["geometry"]),
            "properties": {k: (float(v) if k in numeric and v is not None else v)
                           for k, v in r.items() if k != "geometry"},
        }
        for r in rows[:MAX_MAP_FARMS]
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "truncated": len(rows) > MAX_MAP_FARMS,
        "extent": list(extent) if extent and extent[0] is not None else None,
    }


def archive_exposure_geojson(archive_id: int) -> dict:
    """Typhoon context for the archive map: each exposure summary's
    municipality outline (coloured by its max TCWS signal) and each typhoon's
    track through its bulletins' centre points."""
    with archive_reader_engine().connect() as conn:
        areas = conn.execute(text("""
            SELECT s.typhoon_id, t.name AS typhoon_name, t.year AS typhoon_year, s.province, s.municipality,
                   s.max_signal_level, s.total_exposure_hours, ST_AsGeoJSON(b.boundary_geom, 5) AS geometry
            FROM arc_area_exposure_summary s
            JOIN arc_admin_boundaries b ON b.archive_id = s.archive_id AND b.boundary_id = s.boundary_id
            LEFT JOIN arc_typhoons t ON t.archive_id = s.archive_id AND t.typhoon_id = s.typhoon_id
            WHERE s.archive_id = :aid AND b.boundary_geom IS NOT NULL
        """), {"aid": archive_id}).mappings().all()
        tracks = conn.execute(text("""
            SELECT b.typhoon_id, t.name AS typhoon_name, t.year AS typhoon_year,
                   ST_AsGeoJSON(ST_MakeLine(b.center_geom ORDER BY b.issued_at), 5) AS geometry
            FROM arc_tropical_cyclone_bulletins b
            LEFT JOIN arc_typhoons t ON t.archive_id = b.archive_id AND t.typhoon_id = b.typhoon_id
            WHERE b.archive_id = :aid AND b.center_geom IS NOT NULL
            GROUP BY b.typhoon_id, t.name, t.year
        """), {"aid": archive_id}).mappings().all()

    def feature(r, kind):
        props = {k: (float(v) if k == "total_exposure_hours" and v is not None else v)
                 for k, v in r.items() if k != "geometry"}
        props["kind"] = kind
        return {"type": "Feature", "geometry": json.loads(r["geometry"]), "properties": props}

    return {
        "type": "FeatureCollection",
        "features": [feature(r, "exposure") for r in areas]
                    + [feature(r, "track") for r in tracks if r["geometry"]],
    }
