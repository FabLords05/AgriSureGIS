import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Polygon, Polyline, Circle, Popup, GeoJSON } from "react-leaflet";
import type { Layer } from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import "leaflet/dist/leaflet.css";
import { FarmerRecord } from "./mockData";

interface GISLeafletMapProps {
  farmers: FarmerRecord[];
  selectedFarmId: string | null;
  onSelectFarm: (id: string | null) => void;
  darkMode: boolean;
  filterMunicipality?: string;
}

// Real, approximate town-center coordinates in Camarines Sur, Bicol Region.
const MUNICIPALITY_CENTERS: Record<string, [number, number]> = {
  "Naga City": [13.6218, 123.1948],
  "Pili":      [13.5711, 123.2841],
  "Libmanan":  [13.7133, 123.0725],
  "Sipocot":   [13.7719, 122.9758],
  "Goa":       [13.7024, 123.4986],
  "Lagonoy":   [13.7361, 123.5225],
};

// Simulated typhoon track crossing Camarines Sur from the Pacific (east) side
// toward the Bicol River valley (west) — Goa/Lagonoy (Signal 3) to Naga/Sipocot (Signal 1-2).
const TYPHOON_TRACK: [number, number][] = [
  [13.86, 123.66],
  [13.78, 123.56],
  [13.71, 123.42],
  [13.66, 123.27],
  [13.62, 123.12],
  [13.58, 122.96],
];

const TYPHOON_EYE: [number, number] = TYPHOON_TRACK[2];

const SIGNAL_WIND_RINGS: { center: [number, number]; radiusMeters: number; signal: 1 | 2 | 3 }[] = [
  { center: [13.71, 123.42], radiusMeters: 32000, signal: 3 },
  { center: [13.66, 123.27], radiusMeters: 42000, signal: 2 },
  { center: [13.62, 123.12], radiusMeters: 50000, signal: 1 },
];

const GROWTH_COLORS: Record<string, string> = {
  Seedling:     "#86efac",
  Vegetative:   "#22c55e",
  Reproductive: "#eab308",
  Ripening:     "#f59e0b",
};

const SIGNAL_DOT_COLORS: Record<number, string> = {
  1: "#22c55e",
  2: "#f59e0b",
  3: "#ef4444",
};

const SIGNAL_RING_COLORS: Record<number, string> = {
  1: "#ef4444",
  2: "#f97316",
  3: "#eab308",
};

// Spreads farms belonging to the same municipality into a small grid around
// its real town center so polygons don't overlap on the map.
function farmCenter(farm: FarmerRecord, indexInMunicipality: number): [number, number] {
  const base = MUNICIPALITY_CENTERS[farm.municipality] ?? MUNICIPALITY_CENTERS["Naga City"];
  const col = indexInMunicipality % 3;
  const row = Math.floor(indexInMunicipality / 3);
  const step = 0.018;
  return [base[0] + row * step, base[1] + (col - 1) * step];
}

function farmPolygon(center: [number, number], areaHectare: number): [number, number][] {
  const half = Math.min(0.006, 0.003 + areaHectare * 0.0008);
  const [lat, lng] = center;
  return [
    [lat - half, lng - half],
    [lat - half, lng + half],
    [lat + half, lng + half],
    [lat + half, lng - half],
  ];
}

// Region X (Northern Mindanao) municipality outlines, for spatial context only —
// PSGC codes sourced from the PSA/NAMRIA-derived 2023 dataset. Not used in any
// exposure calculation (ExposureCalculatorService still matches on province/
// municipality/barangay text, per tbl_admin_boundaries having no geom column).
const REGION_X_BOUNDARIES_URL = "/data/region10-boundaries.geojson";

function styleBoundary() {
  return { color: "#166534", weight: 1, opacity: 0.5, fillOpacity: 0, dashArray: "4, 4" };
}

function labelBoundary(feature: Feature, layer: Layer) {
  const { province, municipality } = feature.properties ?? {};
  if (municipality) {
    layer.bindTooltip(`${municipality}, ${province}`, { sticky: true });
  }
}

export function GISLeafletMap({ farmers, selectedFarmId, onSelectFarm, darkMode, filterMunicipality }: GISLeafletMapProps) {
  const [regionXBoundaries, setRegionXBoundaries] = useState<FeatureCollection | null>(null);

  useEffect(() => {
    fetch(REGION_X_BOUNDARIES_URL)
      .then(res => res.json())
      .then(setRegionXBoundaries)
      .catch(() => setRegionXBoundaries(null));
  }, []);

  const visibleFarmers = filterMunicipality
    ? farmers.filter(f => f.municipality === filterMunicipality)
    : farmers;

  const municipalityCounters: Record<string, number> = {};
  const farmPlacements = useMemo(() => {
    const placements = new Map<string, { center: [number, number]; polygon: [number, number][] }>();
    for (const f of visibleFarmers) {
      const idx = municipalityCounters[f.municipality] ?? 0;
      municipalityCounters[f.municipality] = idx + 1;
      const center = farmCenter(f, idx);
      placements.set(f.farmId, { center, polygon: farmPolygon(center, f.areaHectare) });
    }
    return placements;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleFarmers]);

  const selectedFarm = selectedFarmId ? farmers.find(f => f.farmId === selectedFarmId) : null;

  return (
    <div className="relative w-full h-full overflow-hidden rounded-lg border border-border bg-card">
      <MapContainer
        center={[8.38, 124.84]}
        zoom={9}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {regionXBoundaries && (
          <GeoJSON data={regionXBoundaries} style={styleBoundary} onEachFeature={labelBoundary} />
        )}

        <Polyline
          positions={TYPHOON_TRACK}
          pathOptions={{ color: "#ff5200", weight: 3, opacity: 0.85, dashArray: "10, 8" }}
        />

        {SIGNAL_WIND_RINGS.map(ring => (
          <Circle
            key={ring.signal}
            center={ring.center}
            radius={ring.radiusMeters}
            pathOptions={{
              color: SIGNAL_RING_COLORS[ring.signal],
              weight: 1.5,
              opacity: 0.5,
              fillColor: SIGNAL_RING_COLORS[ring.signal],
              fillOpacity: 0.08,
              dashArray: "5, 4",
            }}
          />
        ))}

        <Circle
          center={TYPHOON_EYE}
          radius={4000}
          pathOptions={{ color: "#ff5200", weight: 2.5, fillColor: "#ff5200", fillOpacity: 0.3 }}
        />

        {visibleFarmers.map(farm => {
          const placement = farmPlacements.get(farm.farmId);
          if (!placement) return null;
          const isSelected = farm.farmId === selectedFarmId;
          const color = farm.planted ? (GROWTH_COLORS[farm.growthStage] ?? "#86efac") : "#9ca3af";

          return (
            <Polygon
              key={farm.farmId}
              positions={placement.polygon}
              pathOptions={{
                color: isSelected ? "#ffffff" : color,
                fillColor: color,
                fillOpacity: farm.planted ? 0.55 : 0.25,
                weight: isSelected ? 3 : 1.5,
                dashArray: farm.planted ? undefined : "3, 3",
              }}
              eventHandlers={{
                click: () => onSelectFarm(farm.farmId === selectedFarmId ? null : farm.farmId),
              }}
            >
              <Popup>
                <div className="text-xs space-y-0.5">
                  <p className="font-semibold">{farm.insuredName}</p>
                  <p className="text-muted-foreground">{farm.farmId} · {farm.barangay}, {farm.municipality}</p>
                  <p>Area: <strong>{farm.areaHectare} ha</strong></p>
                  <p>Stage: <strong>{farm.growthStage}</strong></p>
                  <p>Signal: <strong style={{ color: SIGNAL_DOT_COLORS[farm.signalNo] }}>No. {farm.signalNo}</strong></p>
                  {farm.planted && <p>Est. Payment: <strong>₱{farm.indemnityPayment.toLocaleString()}</strong></p>}
                </div>
              </Popup>
            </Polygon>
          );
        })}
      </MapContainer>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md z-[1000]">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Growth Stage</p>
        {Object.entries(GROWTH_COLORS).map(([stage, color]) => (
          <div key={stage} className="flex items-center gap-1.5 mb-0.5">
            <span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: color }} />
            <span className="text-[10px]">{stage}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5 mt-1">
          <span className="w-3 h-3 rounded-sm inline-block bg-gray-400/60" />
          <span className="text-[10px]">Not Planted</span>
        </div>
      </div>

      <div className="absolute bottom-3 left-36 bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md z-[1000]">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Signal No.</p>
        {([1, 2, 3] as const).map(s => (
          <div key={s} className="flex items-center gap-1.5 mb-0.5">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: SIGNAL_DOT_COLORS[s] }} />
            <span className="text-[10px]">Signal {s}</span>
          </div>
        ))}
      </div>

      {/* Selected Farm Info Panel */}
      {selectedFarm && (
        <div className="absolute top-3 left-3 bg-card border-2 border-[#166534] rounded-lg shadow-xl p-3 min-w-[230px] z-[1000]">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-bold text-[#166534] uppercase tracking-wide">Farm Details</span>
            <button onClick={() => onSelectFarm(null)} className="text-muted-foreground hover:text-foreground text-[10px]">✕</button>
          </div>
          <p className="text-[12px] font-semibold">{selectedFarm.insuredName}</p>
          <p className="text-[10px] text-muted-foreground mb-2">{selectedFarm.farmerId}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
            <span className="text-muted-foreground">Farm ID:</span><span className="font-medium">{selectedFarm.farmId}</span>
            <span className="text-muted-foreground">Municipality:</span><span className="font-medium">{selectedFarm.municipality}</span>
            <span className="text-muted-foreground">Barangay:</span><span className="font-medium">{selectedFarm.barangay}</span>
            <span className="text-muted-foreground">Area:</span><span className="font-medium">{selectedFarm.areaHectare} ha</span>
            <span className="text-muted-foreground">Growth Stage:</span>
            <span className="font-medium" style={{ color: GROWTH_COLORS[selectedFarm.growthStage] }}>{selectedFarm.growthStage}</span>
            <span className="text-muted-foreground">Planted:</span><span className="font-medium">{selectedFarm.planted ? "Yes" : "No"}</span>
            <span className="text-muted-foreground">Signal No.:</span>
            <span className="font-bold" style={{ color: SIGNAL_DOT_COLORS[selectedFarm.signalNo] }}>Signal {selectedFarm.signalNo}</span>
            <span className="text-muted-foreground">Exposure:</span><span className="font-medium">{selectedFarm.periodOfExposure}h</span>
            <span className="text-muted-foreground">Ind. Factor:</span><span className="font-medium text-amber-600">{selectedFarm.indemnityFactor}%</span>
            <span className="text-muted-foreground">Payment:</span><span className="font-bold text-[#166534]">₱{selectedFarm.indemnityPayment.toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}
