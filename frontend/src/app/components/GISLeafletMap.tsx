import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, CircleMarker, Marker, Popup, useMap } from "react-leaflet";
import type { Layer } from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.gridlayer.googlemutant";
import { Farm, Assessment, Bulletin, TcbSignal, getBulletinSignals } from "@/lib/api";

const GOOGLE_MAPS_API_KEY: string | undefined = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;

// Bridges the real Google Maps JavaScript API into Leaflet via the googlemutant
// plugin, per Fabio's request for real satellite imagery instead of street tiles.
// The API key is added later by the team that owns it (Fabio's side) -- falls
// back to the existing OpenStreetMap TileLayer whenever no key is set, so the
// map never breaks in the meantime.
function GoogleSatelliteLayer({ apiKey }: { apiKey: string }) {
  const map = useMap();

  useEffect(() => {
    let cancelled = false;
    let layer: L.Layer | null = null;

    const addLayer = () => {
      if (cancelled) return;
      layer = (L as any).gridLayer.googleMutant({ type: "satellite" }).addTo(map);
    };

    if (window.google?.maps) {
      addLayer();
    } else {
      const existing = document.getElementById("google-maps-script") as HTMLScriptElement | null;
      if (existing) {
        existing.addEventListener("load", addLayer);
      } else {
        const script = document.createElement("script");
        script.id = "google-maps-script";
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}`;
        script.async = true;
        script.addEventListener("load", addLayer);
        document.head.appendChild(script);
      }
    }

    return () => {
      cancelled = true;
      if (layer) map.removeLayer(layer);
    };
  }, [map, apiKey]);

  return null;
}

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
function FlyToSelectedFarm({ farm, approxPos }: { farm: FarmRow | null; approxPos: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (!farm) return;
    if (farm.location_geom) {
      const bounds = L.geoJSON(farm.location_geom as any).getBounds();
      if (bounds.isValid()) map.flyToBounds(bounds, { maxZoom: 16, padding: [40, 40] });
    } else if (approxPos) {
      map.flyTo(approxPos, 14);
    }
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

// Spreads farms without real geometry into a small grid around their
// municipality's real town center, so they don't overlap on the map.
function approximateFarmPosition(municipality: string | null, indexInMunicipality: number): [number, number] {
  const base = (municipality && MUNICIPALITY_CENTERS[municipality]) ?? DEFAULT_CENTER;
  const col = indexInMunicipality % 3;
  const row = Math.floor(indexInMunicipality / 3);
  const step = 0.018;
  return [base[0] + row * step, base[1] + (col - 1) * step];
}

export function GISLeafletMap({ farms, selectedFarmId, onSelectFarm, selectedBulletin, darkMode, focusMunicipality }: GISLeafletMapProps) {
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

  const surveyedFarms = farms.filter(f => f.location_geom != null);
  const unsurveyedFarms = farms.filter(f => f.location_geom == null);

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
        />
        <FlyToMunicipality municipality={focusMunicipality ?? null} boundaries={regionXBoundaries} />

        {GOOGLE_MAPS_API_KEY ? (
          <GoogleSatelliteLayer apiKey={GOOGLE_MAPS_API_KEY} />
        ) : (
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
        )}

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
            duplicate info box. */}
        {surveyedFarms.map(farm => {
          const isSelected = farm.farm_id === selectedFarmId;
          return (
            <GeoJSON
              key={farm.farm_id}
              data={farm.location_geom as any}
              style={{
                color: isSelected ? "#ffffff" : "#1e3a5f",
                fillColor: isSelected ? "#f59e0b" : "#1e3a5f",
                fillOpacity: isSelected ? 0.65 : 0.4,
                weight: isSelected ? 3 : 1.5,
              }}
              eventHandlers={{
                click: () => onSelectFarm(farm.farm_id === selectedFarmId ? null : farm.farm_id),
              }}
            />
          );
        })}

        {/* Farms without a GPX boundary yet — approximate placement, click to select as an upload target */}
        {unsurveyedFarms.map(farm => {
          const pos = approxPlacements.get(farm.farm_id);
          if (!pos) return null;
          const isSelected = farm.farm_id === selectedFarmId;
          return (
            <CircleMarker
              key={farm.farm_id}
              center={pos}
              radius={isSelected ? 8 : 6}
              pathOptions={{
                color: isSelected ? "#ffffff" : "#9ca3af",
                fillColor: isSelected ? "#f59e0b" : "#9ca3af",
                fillOpacity: isSelected ? 0.9 : 0.6,
                weight: isSelected ? 3 : 1.5,
              }}
              eventHandlers={{
                click: () => onSelectFarm(farm.farm_id === selectedFarmId ? null : farm.farm_id),
              }}
            />
          );
        })}
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
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: "#1e3a5f" }} />
          <span className="text-[10px]">Surveyed (GPX)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: "#9ca3af" }} />
          <span className="text-[10px]">Approximate (no GPX yet)</span>
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
            <span className="font-medium">{selectedFarm.location_geom ? "Surveyed" : "Not yet uploaded"}</span>
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
