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

        polygon = Polygon(points)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        multipolygon = MultiPolygon([polygon])
        return WKTElement(multipolygon.wkt, srid=4326)
