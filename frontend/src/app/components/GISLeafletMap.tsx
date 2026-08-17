import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, Marker, Popup, useMap, useMapEvents } from "react-leaflet";
import type { Layer } from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Farm, Assessment, Bulletin, TcbSignal, GeoJsonMultiPolygon, getBulletinSignals, getFarmsGeometry } from "@/lib/api";

interface FarmRow extends Farm {
  assessment: Assessment | null;
}

interface GISLeafletMapProps {
  farms: FarmRow[];
  selectedFarmId: number | null;
  onSelectFarm: (id: number | null) => void;
  selectedBulletin: Bulletin | null;
  darkMode: boolean;
  focusMunicipality?: string | null;
  // Passed through to GET /farms/geometry alongside focusMunicipality --
  // matches whatever active-insurance scope SpatialAnalysisModule's Farm
  // Records table is currently using, so the map's polygon layer is scoped
  // the same way (2026-08-18, stage 2 of the on-demand-pagination redesign
  // -- see .claude/FUNCTION_CHANGES.md).
  activeOnly: boolean;
}

// Real, approximate town-center coordinates for the two municipalities actually
// seeded today (per backend/pabs_results.csv: Bukidnon/Talakag and Misamis
// Oriental/Claveria) — used only to place farms that don't yet have a real
// GPX-surveyed boundary.
const MUNICIPALITY_CENTERS: Record<string, [number, number]> = {
  "Talakag":  [8.2158, 124.6547],
  "Claveria": [9.1667, 124.9833],
};
const DEFAULT_CENTER: [number, number] = [8.38, 124.84]; // Region X, between Talakag and Claveria

const SIGNAL_DOT_COLORS: Record<number, string> = {
  2: "#f59e0b",
  3: "#f97316",
  4: "#ef4444",
  5: "#991b1b",
};

// Custom marker via DivIcon (inline SVG) — avoids the well-known Vite/Webpack
// "missing default Leaflet marker icon" asset-resolution issue entirely.
const typhoonIcon = L.divIcon({
  html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="#ff5200" stroke="white" stroke-width="1.5"><circle cx="12" cy="12" r="9"/></svg>`,
  className: "",
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

// Region X (Northern Mindanao) municipality outlines, for spatial context only —
// PSGC codes sourced from the PSA/NAMRIA-derived 2023 dataset. Not used in any
// exposure calculation (ExposureCalculatorService still matches on province/
// municipality/barangay text). Preferred source is GeoServer WFS (live from
// tbl_admin_boundaries.boundary_geom, see .claude/GEOSERVER_SETUP.md); falls back
// to this bundled static file if GeoServer is unset/unreachable.
const REGION_X_BOUNDARIES_URL = "/data/region10-boundaries.geojson";

// Requests go through the Vite dev server's /geoserver-proxy path (see vite.config.ts),
// which forwards to VITE_GEOSERVER_URL server-side — this keeps every GeoServer
// request same-origin from the browser's perspective, so it works without needing
// CORS configured on GeoServer at all.
const GEOSERVER_URL = import.meta.env.VITE_GEOSERVER_URL as string | undefined;
const GEOSERVER_WORKSPACE = "agrisuregis";
const GEOSERVER_PROXY_BASE = "/geoserver-proxy";
const REGION_X_BOUNDARIES_WFS_URL = GEOSERVER_URL
  ? `${GEOSERVER_PROXY_BASE}/${GEOSERVER_WORKSPACE}/ows?service=WFS&version=2.0.0&request=GetFeature&typeName=${GEOSERVER_WORKSPACE}:tbl_admin_boundaries&outputFormat=application/json`
  : null;
const FARMS_WMS_LAYER = `${GEOSERVER_WORKSPACE}:tbl_farms`;
const FARMS_WMS_URL = GEOSERVER_URL ? `${GEOSERVER_PROXY_BASE}/${GEOSERVER_WORKSPACE}/wms` : null;

function styleBoundary() {
  return { color: "#166534", weight: 1, opacity: 0.5, fillOpacity: 0, dashArray: "4, 4" };
}

function labelBoundary(feature: Feature, layer: Layer) {
  const { province, municipality } = feature.properties ?? {};
  if (municipality) {
    layer.bindTooltip(`${municipality}, ${province}`, { sticky: true });
  }
}

// Flies the map to whichever farm is selected -- its real GPX polygon bounds
// if surveyed, otherwise its approximate marker position. Runs inside
// MapContainer since useMap() only works there.
//
// The selected farm's geometry may not be in `geomCache` yet -- geometry is
// now fetched by map viewport (see the geomCache effects below), and a farm
// selected from a table row can be anywhere, not just what's currently
// panned into view. When that happens, this resolves it directly via
// GET /farms/geometry?farm_id=... (see backend/app/api/farms.py) instead of
// waiting for a pan/zoom to bring it into the bbox fetch, and reports the
// result back via onGeometryFetched so it also becomes render-eligible
// immediately rather than only after this flight lands.
function FlyToSelectedFarm({
  farm, approxPos, geomCache, onGeometryFetched,
}: {
  farm: FarmRow | null;
  approxPos: [number, number] | null;
  geomCache: Map<number, GeoJsonMultiPolygon>;
  onGeometryFetched: (farmId: number, geom: GeoJsonMultiPolygon) => void;
}) {
  const map = useMap();
  useEffect(() => {
    if (!farm) return;
    const cached = geomCache.get(farm.farm_id);
    if (cached) {
      const bounds = L.geoJSON(cached as any).getBounds();
      if (bounds.isValid()) map.flyToBounds(bounds, { maxZoom: 16, padding: [40, 40] });
      return;
    }
    if (farm.has_geometry) {
      getFarmsGeometry({ farm_id: farm.farm_id })
        .then(res => {
          const entry = res.data[0];
          if (!entry) return;
          onGeometryFetched(entry.farm_id, entry.location_geom);
          const bounds = L.geoJSON(entry.location_geom as any).getBounds();
          if (bounds.isValid()) map.flyToBounds(bounds, { maxZoom: 16, padding: [40, 40] });
        })
        .catch(() => { /* leave the map where it is on failure */ });
      return;
    }
    if (approxPos) map.flyTo(approxPos, 14);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farm?.farm_id]);
  return null;
}

// Flies the map to a searched/selected municipality's real boundary outline
// (from the same regionXBoundaries GeoJSON used for the dashed context layer),
// same idea as FlyToSelectedFarm but at municipality scale instead of farm scale.
function FlyToMunicipality({ municipality, boundaries }: { municipality: string | null; boundaries: FeatureCollection | null }) {
  const map = useMap();
  useEffect(() => {
    if (!municipality || !boundaries) return;
    const matches = boundaries.features.filter(
      f => (f.properties?.municipality ?? "").toLowerCase() === municipality.toLowerCase()
    );
    if (matches.length === 0) return;
    const bounds = L.geoJSON({ type: "FeatureCollection", features: matches } as FeatureCollection).getBounds();
    if (!bounds.isValid()) return;
    // fitBounds' natural zoom (whatever fits the whole municipality shape) can be
    // quite far out for a large/sprawling municipality -- floor it at 12 so the
    // view never pulls back further than that, even if the shape doesn't fully fit.
    const fitZoom = map.getBoundsZoom(bounds, false, [20, 20]);
    map.flyTo(bounds.getCenter(), Math.max(fitZoom, 12));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [municipality, boundaries]);
  return null;
}

// ---------------------------------------------------------------------------
// Viewport-scoped geometry (2026-08-18, stage 2 of the on-demand-pagination
// redesign -- see .claude/FUNCTION_CHANGES.md). Polygon geometry is fetched
// directly from GET /farms/geometry, scoped to the map's current bbox +
// activeOnly/focusMunicipality (see the geomCache effects below), instead of
// culling client-side over geometry that used to sit on every farm already
// loaded into the shared `farms` array. `farms` no longer carries geometry
// at all (see api.ts's Farm interface) -- only `has_geometry`/attributes.
//
// computeGeoJsonBBox/bboxIntersects are still needed here, just applied to
// the fetched geometry cache instead of the whole farm set: recomputed only
// on moveend/zoomend, Leaflet's own discrete end-of-gesture events, not on
// every continuous move/zoom tick during a drag -- no extra debounce needed.
// ---------------------------------------------------------------------------
interface SimpleBounds { south: number; west: number; north: number; east: number; }

function toSimpleBounds(b: L.LatLngBounds): SimpleBounds {
  return { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() };
}

// [minLng, minLat, maxLng, maxLat] -- plain numbers, not a Leaflet object, so
// caching one per farm (up to ~48,588) doesn't mean allocating that many
// Leaflet LatLngBounds instances.
type BBox = [number, number, number, number];

function computeGeoJsonBBox(geom: GeoJsonMultiPolygon): BBox {
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
  for (const polygon of geom.coordinates) {
    for (const ring of polygon) {
      for (const [lng, lat] of ring) {
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      }
    }
  }
  return [minLng, minLat, maxLng, maxLat];
}

function bboxIntersects(bbox: BBox, bounds: SimpleBounds): boolean {
  const [minLng, minLat, maxLng, maxLat] = bbox;
  return maxLng >= bounds.west && minLng <= bounds.east && maxLat >= bounds.south && minLat <= bounds.north;
}

// Reports the map's current bounds on mount (the real, pixel-derived initial
// viewport for MapContainer's center/zoom props -- not a guessed one, since
// by the time this child mounts inside MapContainer the underlying Leaflet
// map instance already exists) and again on every moveend/zoomend.
function MapBoundsWatcher({ onBoundsChange }: { onBoundsChange: (b: L.LatLngBounds) => void }) {
  const map = useMap();
  useEffect(() => {
    onBoundsChange(map.getBounds());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);
  useMapEvents({
    moveend: () => onBoundsChange(map.getBounds()),
    zoomend: () => onBoundsChange(map.getBounds()),
  });
  return null;
}

// Spreads farms without real geometry into a small grid around their
// municipality's real town center, so they don't overlap on the map.
function approximateFarmPosition(municipality: string | null, indexInMunicipality: number): [number, number] {
  const base = (municipality && MUNICIPALITY_CENTERS[municipality]) ?? DEFAULT_CENTER;
  const col = indexInMunicipality % 3;
  const row = Math.floor(indexInMunicipality / 3);
  const step = 0.018;
  return [base[0] + row * step, base[1] + (col - 1) * step];
}

export function GISLeafletMap({ farms, selectedFarmId, onSelectFarm, selectedBulletin, darkMode, focusMunicipality, activeOnly }: GISLeafletMapProps) {
  const [affectedAreas, setAffectedAreas] = useState<TcbSignal[]>([]);
  const [regionXBoundaries, setRegionXBoundaries] = useState<FeatureCollection | null>(null);
  const [showFarmsWmsOverlay, setShowFarmsWmsOverlay] = useState(false);

  useEffect(() => {
    if (!selectedBulletin) {
      setAffectedAreas([]);
      return;
    }
    getBulletinSignals(selectedBulletin.tcb_id)
      .then(setAffectedAreas)
      .catch(() => setAffectedAreas([]));
  }, [selectedBulletin]);

  useEffect(() => {
    const loadStaticFallback = () =>
      fetch(REGION_X_BOUNDARIES_URL)
        .then(res => res.json())
        .then(setRegionXBoundaries)
        .catch(() => setRegionXBoundaries(null));

    if (!REGION_X_BOUNDARIES_WFS_URL) {
      loadStaticFallback();
      return;
    }
    fetch(REGION_X_BOUNDARIES_WFS_URL)
      .then(res => {
        if (!res.ok) throw new Error(`GeoServer WFS request failed: ${res.status}`);
        return res.json();
      })
      .then(setRegionXBoundaries)
      .catch(loadStaticFallback);
  }, []);

  const unsurveyedFarms = useMemo(() => farms.filter(f => !f.has_geometry), [farms]);

  const municipalityCounters: Record<string, number> = {};
  const approxPlacements = useMemo(() => {
    const placements = new Map<number, [number, number]>();
    for (const f of unsurveyedFarms) {
      const key = f.municipality ?? "__unknown__";
      const idx = municipalityCounters[key] ?? 0;
      municipalityCounters[key] = idx + 1;
      placements.set(f.farm_id, approximateFarmPosition(f.municipality, idx));
    }
    return placements;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unsurveyedFarms]);

  // The map's current visible bounds -- null until MapBoundsWatcher's mount
  // effect reports the real initial viewport (see its comment). While null,
  // the render list below resolves to [] rather than "everything," since
  // showing nothing for the single commit before that effect fires is
  // imperceptible, whereas a brief "everything" render would reintroduce
  // exactly the perf problem this fix removes.
  const [mapBounds, setMapBounds] = useState<SimpleBounds | null>(null);
  const handleBoundsChange = useCallback((b: L.LatLngBounds) => setMapBounds(toSimpleBounds(b)), []);

  // Polygon geometry cache -- keyed by farm_id, populated by GET
  // /farms/geometry (see the effects below), not by anything already
  // sitting on the `farms` prop. Reset (not merged) whenever
  // activeOnly/focusMunicipality change, since a stale/mismatched polygon
  // under the new filters is worse than one extra round trip; merged
  // in-place as new bbox pages/single-farm lookups land otherwise.
  const [geomCache, setGeomCache] = useState<Map<number, GeoJsonMultiPolygon>>(new Map());

  useEffect(() => {
    setGeomCache(new Map());
  }, [activeOnly, focusMunicipality]);

  const bboxString = mapBounds
    ? `${mapBounds.west},${mapBounds.south},${mapBounds.east},${mapBounds.north}`
    : null;

  useEffect(() => {
    if (!bboxString) return;
    getFarmsGeometry({ bbox: bboxString, active_only: activeOnly, municipality: focusMunicipality ?? undefined })
      .then(res => {
        setGeomCache(prev => {
          const next = new Map(prev);
          for (const { farm_id, location_geom } of res.data) next.set(farm_id, location_geom);
          return next;
        });
      })
      .catch(() => { /* leave the cache as-is on failure -- next moveend/zoomend retries */ });
  }, [bboxString, activeOnly, focusMunicipality]);

  // Rendered-layer set -- viewport-culled subset of geomCache, used ONLY by
  // the polygon render loop below. Deliberately NOT used for `selectedFarm`,
  // `approxPlacements`, FlyToSelectedFarm, or the legend -- those must keep
  // working regardless of what's currently panned into view (e.g. clicking a
  // table row for a farm outside the current viewport still needs to
  // resolve and fly to it; flyTo's own moveend at the end of that animation
  // is what brings the farm into this list once the camera actually lands).
  const visibleGeomEntries = useMemo(() => {
    if (!mapBounds) return [];
    const entries: { farmId: number; geom: GeoJsonMultiPolygon }[] = [];
    for (const [farmId, geom] of geomCache) {
      if (bboxIntersects(computeGeoJsonBBox(geom), mapBounds)) entries.push({ farmId, geom });
    }
    return entries;
  }, [geomCache, mapBounds]);

  const selectedFarm = selectedFarmId != null ? farms.find(f => f.farm_id === selectedFarmId) : null;
  const uniqueAffectedAreas = Array.from(new Set(affectedAreas.map(s => s.area_name)));

  // The map's attribution links (Leaflet's own "Leaflet" credit + the OSM copyright
  // link below) default to same-tab navigation. Since this SPA has no URL routing,
  // clicking them navigates the whole app away — hitting Back afterward reloads the
  // app from scratch and drops the user back on the login screen instead of where
  // they were. Force every attribution link to open in a new tab instead.
  const mapWrapperRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const wrapper = mapWrapperRef.current;
    if (!wrapper) return;
    const patchLinks = () => {
      wrapper.querySelectorAll(".leaflet-control-attribution a").forEach(a => {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
      });
    };
    patchLinks();
    const observer = new MutationObserver(patchLinks);
    observer.observe(wrapper, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={mapWrapperRef} className="relative w-full h-full overflow-hidden rounded-lg border border-border bg-card">
      <MapContainer
        center={DEFAULT_CENTER}
        zoom={9}
        style={{ height: "100%", width: "100%" }}
      >
        <FlyToSelectedFarm
          farm={selectedFarm}
          approxPos={selectedFarm ? approxPlacements.get(selectedFarm.farm_id) ?? null : null}
          geomCache={geomCache}
          onGeometryFetched={(farmId, geom) => setGeomCache(prev => new Map(prev).set(farmId, geom))}
        />
        <FlyToMunicipality municipality={focusMunicipality ?? null} boundaries={regionXBoundaries} />
        <MapBoundsWatcher onBoundsChange={handleBoundsChange} />

        {/* Esri World Imagery -- free, no API key/billing required. High-resolution
            (often sub-meter in populated/agricultural areas), curated best-available
            mosaic so it reads as cloud-free in practice. Replaced the earlier
            Google Maps/googlemutant satellite layer (needed a billing-enabled GCP
            key that was never provisioned) and the OpenStreetMap street tiles it
            fell back to. */}
        <TileLayer
          attribution='Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener noreferrer">Esri</a> — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        />

        {/* Optional GeoServer WMS reference overlay for farm boundaries — additive only,
            the interactive farm layer below (click/popup, from FastAPI) is unaffected. */}
        {showFarmsWmsOverlay && FARMS_WMS_URL && (
          <WMSTileLayer
            url={FARMS_WMS_URL}
            layers={FARMS_WMS_LAYER}
            format="image/png"
            transparent
            opacity={0.6}
          />
        )}

        {regionXBoundaries && (
          <GeoJSON data={regionXBoundaries} style={styleBoundary} onEachFeature={labelBoundary} />
        )}

        {/* Real typhoon marker + affected-area list (no track/radius geometry exists in the DB) */}
        {selectedBulletin?.center_lat != null && selectedBulletin?.center_lng != null && (
          <Marker position={[selectedBulletin.center_lat, selectedBulletin.center_lng]} icon={typhoonIcon}>
            <Popup>
              <div className="text-xs space-y-0.5">
                <p className="font-semibold">{selectedBulletin.typhoon_name}</p>
                <p className="text-muted-foreground">{selectedBulletin.category ?? "Unknown category"}</p>
                <p>Max winds: <strong>{selectedBulletin.max_sustained_winds ?? "—"} km/h</strong></p>
                <p className="mt-1 font-medium">Affected areas:</p>
                <ul className="list-disc pl-4">
                  {uniqueAffectedAreas.length > 0
                    ? uniqueAffectedAreas.map(area => <li key={area}>{area}</li>)
                    : <li className="text-muted-foreground">No signal data recorded</li>
                  }
                </ul>
              </div>
            </Popup>
          </Marker>
        )}

        {/* Real GPX-surveyed farm boundaries. No click-popup here -- the Selected
            Farm Info Panel overlay already shows this same (and more) detail,
            so clicking just selects/highlights instead of also popping up a
            duplicate info box.

            Geometry (viewport-fetched) and attributes (loaded into the Farm
            Records table) now arrive independently, so a polygon can render
            for a farm_id the table hasn't loaded attributes for yet.
            Rendered the same either way -- clicking still selects it, and
            the Selected Farm Info Panel below already renders gracefully
            with missing attrs ("Unknown farmer", "—" placeholders) -- real
            geometry the backend already returned is never skipped just
            because attributes haven't caught up. */}
        {visibleGeomEntries.map(({ farmId, geom }) => {
          const isSelected = farmId === selectedFarmId;
          return (
            <GeoJSON
              key={farmId}
              data={geom as any}
              style={{
                color: isSelected ? "#ffffff" : "#1e3a5f",
                fillColor: isSelected ? "#f59e0b" : "#1e3a5f",
                fillOpacity: isSelected ? 0.65 : 0.4,
                weight: isSelected ? 3 : 1.5,
              }}
              eventHandlers={{
                click: () => onSelectFarm(farmId === selectedFarmId ? null : farmId),
              }}
            />
          );
        })}

        {/* Farms without a GPX boundary yet are intentionally not rendered here
            (removed 2026-08-11 -- with almost the entire farm table lacking real
            geometry, MUNICIPALITY_CENTERS' shared fallback points meant thousands
            of farms collapsed into a few solid-looking blobs, not real locations).
            approxPlacements (below) is kept -- selecting one of these farms from
            the table still flies the map to its approximate town-center position,
            just without drawing a marker there. */}
      </MapContainer>

      {/* GeoServer WMS overlay toggle — only shown when VITE_GEOSERVER_URL is configured */}
      {GEOSERVER_URL && (
        <label className="absolute top-3 right-3 flex items-center gap-1.5 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md z-[1000] text-[10px] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showFarmsWmsOverlay}
            onChange={e => setShowFarmsWmsOverlay(e.target.checked)}
          />
          GeoServer farm overlay
        </label>
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md z-[1000]">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Farm Boundary</p>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: "#1e3a5f" }} />
          <span className="text-[10px]">Surveyed (GPX)</span>
        </div>
      </div>

      {selectedBulletin && (
        <div className="absolute bottom-3 left-52 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md z-[1000] max-w-[180px]">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Signal</p>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full inline-block" style={{ backgroundColor: "#ff5200" }} />
            <span className="text-[10px]">{selectedBulletin.typhoon_name} center</span>
          </div>
        </div>
      )}

      {/* Selected Farm Info Panel */}
      {selectedFarm && (
        <div className="absolute top-3 left-3 bg-card border-2 border-[#166534] rounded-lg shadow-xl p-3 min-w-[230px] z-[1000]">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-bold text-[#166534] uppercase tracking-wide">Farm Details</span>
            <button onClick={() => onSelectFarm(null)} className="text-muted-foreground hover:text-foreground text-[10px]">✕</button>
          </div>
          <p className="text-[12px] font-semibold">{selectedFarm.farmer_name ?? "Unknown farmer"}</p>
          <p className="text-[10px] text-muted-foreground mb-2">Farm #{selectedFarm.farm_id}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
            <span className="text-muted-foreground">Municipality:</span><span className="font-medium">{selectedFarm.municipality ?? "—"}</span>
            <span className="text-muted-foreground">Barangay:</span><span className="font-medium">{selectedFarm.barangay ?? "—"}</span>
            <span className="text-muted-foreground">Area:</span><span className="font-medium">{selectedFarm.area_size ?? "—"} ha</span>
            <span className="text-muted-foreground">GPX Boundary:</span>
            <span className="font-medium">{selectedFarm.has_geometry ? "Surveyed" : "Not yet uploaded"}</span>
            {selectedFarm.assessment && (
              <>
                <span className="text-muted-foreground">Crop Stage:</span><span className="font-medium">{selectedFarm.assessment.crop_stage ?? "—"}</span>
                <span className="text-muted-foreground">Signal No.:</span>
                <span className="font-bold" style={{ color: selectedFarm.assessment.wind_velocity ? SIGNAL_DOT_COLORS[selectedFarm.assessment.wind_velocity] : undefined }}>
                  {selectedFarm.assessment.wind_velocity ? `Signal ${selectedFarm.assessment.wind_velocity}` : "—"}
                </span>
                <span className="text-muted-foreground">Exposure:</span><span className="font-medium">{selectedFarm.assessment.period_of_exposure ?? "—"}h</span>
                <span className="text-muted-foreground">Payment:</span>
                <span className="font-bold text-[#166534]">₱{selectedFarm.assessment.final_indemnity_payment.toLocaleString()}</span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
