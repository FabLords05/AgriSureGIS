import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import shapely
from geoalchemy2.elements import WKTElement

from app.services.gpx_farmer_matcher import GpxFarmerMatcherService, ParsedGpxFilename
from app.services.gpx_parser import to_multipolygon_wkt

# GeoPackage geometry blob header (OGC GeoPackage spec, "GeoPackageBinary"):
# 2-byte "GP" magic, version byte, flags byte, 4-byte srs_id, then an optional
# envelope whose size depends on bits 1-3 of the flags byte, then standard WKB.
_GPKG_HEADER_BYTES = 8
_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}

# Real file_name values in the client's export don't share one date format --
# "..._2024-01-29.gpx", "..._2025-8-29.gpx", "..._2024-10-02_0144ad.gpx" -- so
# match leniently and take the last date-looking run in the name.
_WALK_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _normalize_column(name: str) -> str:
    """Same bare-alphanumeric collapse upload.py's _normalize_header() applies to
    CSV headers, so 'FARMER NAME' / 'farmer_name' / 'FarmerName' all resolve."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _clean_text(value) -> str | None:
    """Attributes are TEXT in the client's file, but a GeoPackage written by a
    different tool may store an ID as INTEGER/REAL -- coerce to the same text
    form the CSV ingest stores (see upload.py's _stringify_id)."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _gpkg_blob_to_geometry(blob):
    if blob is None:
        raise ValueError("Feature has no geometry.")
    blob = bytes(blob)
    if len(blob) < _GPKG_HEADER_BYTES or blob[:2] != b"GP":
        raise ValueError("Feature geometry is not a GeoPackage geometry blob.")

    flags = blob[3]
    if flags & 0b0010_0000:
        raise ValueError("Extended GeoPackage geometry types are not supported.")
    if flags & 0b0001_0000:
        raise ValueError("Feature geometry is empty.")

    envelope_type = (flags >> 1) & 0b111
    if envelope_type not in _ENVELOPE_BYTES:
        raise ValueError(f"Invalid GeoPackage envelope type {envelope_type}.")

    geometry = shapely.from_wkb(blob[_GPKG_HEADER_BYTES + _ENVELOPE_BYTES[envelope_type]:])
    # tbl_farms.location_geom is 2D -- drop any Z/M a surveying tool may have written.
    return shapely.force_2d(geometry)


def _parse_walk_date(file_name: str | None) -> date | None:
    if not file_name:
        return None
    matches = _WALK_DATE_RE.findall(file_name)
    if not matches:
        return None
    year, month, day = matches[-1]
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


@dataclass
class GpkgFeature:
    fid: int
    file_name: str | None
    farmers_id: str | None
    farm_reference: str | None
    farmer_name: str | None
    geom_blob: bytes | None

    @property
    def walk_date(self) -> date | None:
        return _parse_walk_date(self.file_name)

    @property
    def label(self) -> str:
        """How this feature is identified in a failure message -- the original
        GPX file name is what the client will recognize."""
        return self.file_name or f"feature {self.fid}"

    def to_location_geom(self) -> WKTElement:
        return to_multipolygon_wkt(_gpkg_blob_to_geometry(self.geom_blob))

    def to_match_input(self) -> ParsedGpxFilename:
        """Feeds GpxFarmerMatcherService the same signals a GPX filename carries
        (FarmersID, FARMID, farmer name), read from the feature's attributes."""
        last_name, first_name, middle_initial = GpxFarmerMatcherService.parse_farmer_name(self.farmer_name or "")
        return ParsedGpxFilename(
            last_name=last_name,
            first_name=first_name,
            middle_initial=middle_initial,
            id1=self.farmers_id,
            id2=self.farm_reference,
        )


class GpkgParserService:
    """
    Reads farm boundary polygons out of a GeoPackage (.gpkg) -- the format the
    client's real boundary data arrives in (e.g. docs/PCICX GPX_EXISTING IC
    AFFECTED BY TY TINO_11-05-2025.gpkg: one layer, one feature per originally
    walked GPX file, carrying FARMERSID/FARMID/FARMER NAME/file_name
    attributes). A GeoPackage is a SQLite database, so this reads it with the
    stdlib sqlite3 module and decodes geometry with shapely -- no GDAL/pyogrio
    dependency needed.
    """

    @staticmethod
    def parse_gpkg_features(path: str | Path) -> list[GpkgFeature]:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            raise ValueError(f"Unable to open GeoPackage: {exc}") from exc

        try:
            try:
                layers = conn.execute(
                    """
                    SELECT gc.table_name, gc.column_name, gc.srs_id,
                           srs.organization, srs.organization_coordsys_id
                    FROM gpkg_geometry_columns gc
                    JOIN gpkg_contents c ON c.table_name = gc.table_name
                    LEFT JOIN gpkg_spatial_ref_sys srs ON srs.srs_id = gc.srs_id
                    WHERE c.data_type = 'features'
                    """
                ).fetchall()
            except sqlite3.DatabaseError as exc:
                raise ValueError("File is not a valid GeoPackage.") from exc

            if not layers:
                raise ValueError("GeoPackage has no feature layers.")

            features: list[GpkgFeature] = []
            for table_name, geom_column, srs_id, organization, coordsys_id in layers:
                is_wgs84 = srs_id == 4326 or (
                    (organization or "").upper() == "EPSG" and coordsys_id == 4326
                )
                if not is_wgs84:
                    raise ValueError(
                        f'Layer "{table_name}" uses SRS {srs_id}; farm boundaries must be in EPSG:4326 (WGS 84).'
                    )
                features.extend(GpkgParserService._read_layer(conn, table_name, geom_column))
            return features
        finally:
            conn.close()

    @staticmethod
    def _read_layer(conn: sqlite3.Connection, table_name: str, geom_column: str) -> list[GpkgFeature]:
        table_info = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
        columns = {_normalize_column(row[1]): row[1] for row in table_info}
        pk_column = next((row[1] for row in table_info if row[5] == 1), "rowid")

        def column_sql(*names: str) -> str:
            for name in names:
                actual = columns.get(_normalize_column(name))
                if actual is not None:
                    return _quote_identifier(actual)
            return "NULL"

        farm_reference_sql = column_sql("FARMID", "parsed_id")
        farmers_id_sql = column_sql("FARMERSID")
        if farm_reference_sql == "NULL" and farmers_id_sql == "NULL":
            raise ValueError(
                f'Layer "{table_name}" has neither a FARMID nor a FARMERSID column to match farms by.'
            )

        rows = conn.execute(
            f"SELECT {_quote_identifier(pk_column)}, {column_sql('file_name')}, {farmers_id_sql}, "
            f"{farm_reference_sql}, {column_sql('FARMER NAME')}, {_quote_identifier(geom_column)} "
            f"FROM {_quote_identifier(table_name)}"
        ).fetchall()

        return [
            GpkgFeature(
                fid=fid,
                file_name=_clean_text(file_name),
                farmers_id=_clean_text(farmers_id),
                farm_reference=_clean_text(farm_reference),
                farmer_name=_clean_text(farmer_name),
                geom_blob=geom_blob,
            )
            for fid, file_name, farmers_id, farm_reference, farmer_name, geom_blob in rows
        ]

    @staticmethod
    def dedupe_by_farm_reference(features: list[GpkgFeature]) -> tuple[list[GpkgFeature], list[GpkgFeature]]:
        """
        The same FARMID can appear more than once -- in the client's real file,
        13 farms do: either an exact re-export of the same walk, or the same farm
        re-walked on a later date. Keeps the most recent walk per FARMID (walk
        date from file_name, falling back to the later feature in the file when
        the date can't be read). Returns (kept, skipped_duplicates); features with
        no FARMID are always kept and left to the matcher's other signals.
        """
        winners: dict[str, GpkgFeature] = {}
        for feature in features:
            if not feature.farm_reference:
                continue
            current = winners.get(feature.farm_reference)
            if current is None or _recency_key(feature) > _recency_key(current):
                winners[feature.farm_reference] = feature

        kept: list[GpkgFeature] = []
        skipped: list[GpkgFeature] = []
        for feature in features:
            if not feature.farm_reference or winners[feature.farm_reference] is feature:
                kept.append(feature)
            else:
                skipped.append(feature)
        return kept, skipped


def _recency_key(feature: GpkgFeature) -> tuple[date, int]:
    return (feature.walk_date or date.min, feature.fid)
