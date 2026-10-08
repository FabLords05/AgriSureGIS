import gpxpy
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.elements import WKTElement


class GpxParserService:
    @staticmethod
    def parse_gpx_to_polygon(gpx_file) -> WKTElement:
        """
        Parses an uploaded GPX file (file-like object or path) into a farm boundary
        polygon. Farm boundaries are captured as a single walked GPS track, so all
        track points across the file's tracks/segments are treated as one ring
        (falling back to route points if the file has no tracks).
        """
        gpx = gpxpy.parse(gpx_file)

        points = [
            (point.longitude, point.latitude)
            for track in gpx.tracks
            for segment in track.segments
            for point in segment.points
        ]

        if not points:
            points = [
                (point.longitude, point.latitude)
                for route in gpx.routes
                for point in route.points
            ]

        if len(points) < 3:
            raise ValueError(
                "GPX file must contain at least 3 track points to form a farm boundary polygon."
            )

        if points[0] != points[-1]:
            points.append(points[0])

        return to_multipolygon_wkt(Polygon(points))


def to_multipolygon_wkt(geometry) -> WKTElement:
    """
    Normalizes a farm boundary geometry (Polygon or MultiPolygon) into the
    MultiPolygon/SRID 4326 shape tbl_farms.location_geom stores. Shared by the
    GPX parser above and GpkgParserService -- the client's real GeoPackage mixes
    Polygon and MultiPolygon features under one layer. buffer(0) repairs an
    invalid (e.g. self-intersecting walked) ring, and can itself hand back a
    MultiPolygon, so both shapes are handled after the repair too.
    """
    if not geometry.is_valid:
        geometry = geometry.buffer(0)

    if geometry.is_empty:
        raise ValueError("Farm boundary polygon is empty.")

    if isinstance(geometry, Polygon):
        geometry = MultiPolygon([geometry])
    elif not isinstance(geometry, MultiPolygon):
        raise ValueError(f"Farm boundary must be a polygon, got {geometry.geom_type}.")

    return WKTElement(geometry.wkt, srid=4326)
