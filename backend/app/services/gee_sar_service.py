"""
Google Earth Engine (GEE) Sentinel-1 layer for the "Verify Farm Planted" use
case -- Phase 1 of docs/SAR_ISPLANTED_METHOD.md (2026-10-12).

Phase 1 is visual only: a pre-event VV/VH-ratio colour layer clipped to the
"Affected Only" farm polygons, which the GIS Specialist reads by eye (green =
canopy closed = planted; tan/brown = sparse/bare/flooded) and then records a
verdict via app/api/sar.py. The per-farm 5-condition isPlanted rule and the
area-planted percentage (method doc §3, §3.2) are Phase 2 and are NOT here.

Same "no-op unless configured" philosophy as email_alert_service.py's SMTP:
without GEE_SERVICE_ACCOUNT_KEY_PATH in backend/.env nothing here touches
Earth Engine, and `ee` is imported lazily so a backend without
earthengine-api installed still starts.

The key file is a live private key (webgis-pcic-*.json, gitignored). Only its
`client_email` and `project_id` are ever read out of it for display -- the
key itself never leaves this process.
"""
import json
import logging
import os
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("agrisuregis.gee_sar")

# Pre-event window (method doc §8): a post-event image conflates "never
# planted" with "flattened by the storm". 24 days ~= two 12-day Sentinel-1
# acquisitions; the end is exclusive, so the last usable day is event - 1d.
PRE_EVENT_WINDOW_DAYS = 24

# Inward buffer before sampling (method doc §5.2) -- keeps bunds, roads and
# neighbouring fields out of the colour. A farm smaller than this simply
# shows no colour; Phase 2 is where that gets flagged as low confidence.
INWARD_BUFFER_M = 20

# Speckle substitute for MAPscape-RICE's temporal smoothing (method doc §5.1).
FOCAL_MEDIAN_RADIUS_M = 30

# VV/VH ratio stretch, dB (method doc §7, from Villano et al. 2019's observed
# range). Low ratio = closed canopy = planted.
RATIO_MIN_DB = 4.5
RATIO_MAX_DB = 7.5
RATIO_PALETTE = ["14532d", "22c55e", "d2b48c", "7c4a1e"]  # deep green -> green -> tan -> brown

# getMapId tile URLs expire after a while; reuse one for an hour so reopening
# the panel doesn't re-run (and re-bill) the same composite.
_LAYER_CACHE_TTL_SECONDS = 3600

_init_lock = threading.Lock()
_initialized = False
_last_error: str | None = None
_last_failed_attempt: float | None = None
# GET /api/system/status is polled by the Monitoring dashboard; after a
# failed sign-in, don't retry Earth Engine on every poll.
_RETRY_AFTER_FAILURE_SECONDS = 300
_layer_cache: dict[tuple, tuple[float, dict]] = {}


class GeeNotConfiguredError(RuntimeError):
    pass


class NoScenesError(RuntimeError):
    pass


def _key_path() -> str | None:
    return os.getenv("GEE_SERVICE_ACCOUNT_KEY_PATH") or None


def _key_identity() -> dict | None:
    """client_email + project_id from the key file -- never the key itself."""
    path = _key_path()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {"service_account": data.get("client_email"), "project_id": data.get("project_id")}
    except (OSError, ValueError) as exc:
        return {"service_account": None, "project_id": None, "error": f"Cannot read key file: {exc}"}


def gee_configured() -> bool:
    """Whether GEE_SERVICE_ACCOUNT_KEY_PATH is set. Does not contact Earth Engine."""
    return _key_path() is not None


def _ensure_initialized():
    """Lazy, process-wide ee.Initialize(). Returns the `ee` module."""
    global _initialized, _last_error, _last_failed_attempt
    if not gee_configured():
        raise GeeNotConfiguredError("GEE_SERVICE_ACCOUNT_KEY_PATH is not set in backend/.env.")
    try:
        import ee  # lazy: earthengine-api is optional until GEE is configured
    except ImportError as exc:
        _last_error = "earthengine-api is not installed in the backend environment."
        raise GeeNotConfiguredError(_last_error) from exc

    with _init_lock:
        if _initialized:
            return ee
        if (
            _last_failed_attempt is not None
            and time.monotonic() - _last_failed_attempt < _RETRY_AFTER_FAILURE_SECONDS
        ):
            raise GeeNotConfiguredError(_last_error or "Earth Engine initialization failed recently.")
        identity = _key_identity() or {}
        if identity.get("error"):
            _last_error = identity["error"]
            _last_failed_attempt = time.monotonic()
            raise GeeNotConfiguredError(_last_error)
        try:
            credentials = ee.ServiceAccountCredentials(identity["service_account"], _key_path())
            ee.Initialize(credentials=credentials, project=identity["project_id"])
        except Exception as exc:  # ee raises EEException and google-auth errors alike
            _last_error = f"Earth Engine initialization failed: {exc}"
            _last_failed_attempt = time.monotonic()
            logger.warning(_last_error)
            raise GeeNotConfiguredError(_last_error) from exc
        _initialized = True
        _last_error = None
        _last_failed_attempt = None
        logger.info("Earth Engine initialized for project %s.", identity["project_id"])
        return ee


def gee_status() -> dict:
    """For GET /api/system/status's `gee` block. Attempts initialization once
    so the Settings card can show a real Connected / error state."""
    identity = _key_identity() or {}
    connected = False
    if gee_configured():
        try:
            _ensure_initialized()
            connected = True
        except GeeNotConfiguredError:
            connected = False
    return {
        "configured": gee_configured(),
        "connected": connected,
        "project_id": identity.get("project_id"),
        "service_account": identity.get("service_account"),
        "last_error": _last_error or identity.get("error"),
    }


def pre_event_window(event_date: date) -> tuple[date, date]:
    """[start, end) for ee filterDate -- end is exclusive, so the last
    scene day included is event_date - 1."""
    return event_date - timedelta(days=PRE_EVENT_WINDOW_DAYS), event_date


def pick_relative_orbit(histogram: dict) -> int | None:
    """Most frequent relative orbit over the AOI (method doc §5.1: holding to
    one orbit keeps incidence angle comparable). Ties go to the lowest orbit
    number so the choice is deterministic. `histogram` is ee's
    aggregate_histogram output: {"<orbit>": count}."""
    if not histogram:
        return None
    counts = Counter({int(float(k)): int(v) for k, v in histogram.items()})
    return min(counts, key=lambda orbit: (-counts[orbit], orbit))


def build_planted_layer(cache_key: tuple, farm_geojsons: list[dict], event_date: date) -> dict:
    """
    Pre-event Sentinel-1 VV/VH-ratio composite clipped to the given farm
    polygons, as an XYZ tile URL.

    Returns {tile_url, scene_dates, relative_orbit, window_start, window_end,
    min_db, max_db, palette}. Raises GeeNotConfiguredError, NoScenesError.
    """
    cached = _layer_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _LAYER_CACHE_TTL_SECONDS:
        return cached[1]

    ee = _ensure_initialized()
    start, end = pre_event_window(event_date)

    farms = ee.FeatureCollection([ee.Feature(ee.Geometry(g)) for g in farm_geojsons])
    region = farms.geometry().bounds()

    scenes = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(region)
        .filterDate(start.isoformat(), end.isoformat())
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )

    orbit = pick_relative_orbit(scenes.aggregate_histogram("relativeOrbitNumber_start").getInfo())
    if orbit is None:
        raise NoScenesError(
            f"No descending Sentinel-1 IW scenes over the affected farms between "
            f"{start.isoformat()} and {(end - timedelta(days=1)).isoformat()}."
        )
    scenes = scenes.filter(ee.Filter.eq("relativeOrbitNumber_start", orbit))
    scene_dates = sorted({
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
        for ms in scenes.aggregate_array("system:time_start").getInfo()
    })

    # COPERNICUS/S1_GRD is already in dB, so VV - VH is the VV/VH ratio in dB.
    composite = (
        scenes.select(["VV", "VH"])
        .map(lambda img: img.focal_median(FOCAL_MEDIAN_RADIUS_M, "circle", "meters"))
        .median()
    )
    ratio = composite.select("VV").subtract(composite.select("VH")).rename("vv_vh_ratio")
    buffered = farms.map(lambda f: f.buffer(-INWARD_BUFFER_M))
    clipped = ratio.clipToCollection(buffered)

    map_id = clipped.getMapId({"min": RATIO_MIN_DB, "max": RATIO_MAX_DB, "palette": RATIO_PALETTE})
    result = {
        "tile_url": map_id["tile_fetcher"].url_format,
        "scene_dates": scene_dates,
        "relative_orbit": orbit,
        "window_start": start.isoformat(),
        "window_end": (end - timedelta(days=1)).isoformat(),
        "min_db": RATIO_MIN_DB,
        "max_db": RATIO_MAX_DB,
        "palette": [f"#{c}" for c in RATIO_PALETTE],
    }
    _layer_cache[cache_key] = (time.monotonic(), result)
    return result
