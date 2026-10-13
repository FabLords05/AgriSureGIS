import { Fragment, useEffect, useState } from "react";
import { Circle, CircleMarker, Marker, Polygon, Polyline, Popup, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import type { TyphoonTrack, TyphoonTrackPoint } from "@/lib/api";

// Typhoon track overlay (2026-10-12) for the Spatial Analysis map: every
// bulletin center of a typhoon, the wind circulation radius around each one,
// the latest bulletin's forecast path, and the PAR outline. Symbols and the
// two radius circles follow the legend on PAGASA's TCB track map.

// Severity scale, lowest to highest: orange for the weakest, red for the
// strongest, opacity rising with intensity.
interface CategoryStyle {
  label: string;
  color: string;
  opacity: number;
  symbol: "L" | "D" | "S" | "T" | "sts" | "sty";
}

const CATEGORY_STYLES: CategoryStyle[] = [
  { label: "Low Pressure Area",     color: "#fdba74", opacity: 0.45, symbol: "L" },
  { label: "Tropical Depression",   color: "#fb923c", opacity: 0.55, symbol: "D" },
  { label: "Tropical Storm",        color: "#f97316", opacity: 0.65, symbol: "S" },
  { label: "Severe Tropical Storm", color: "#ea580c", opacity: 0.75, symbol: "sts" },
  { label: "Typhoon",               color: "#dc2626", opacity: 0.88, symbol: "T" },
  { label: "Super Typhoon",         color: "#991b1b", opacity: 1,    symbol: "sty" },
];
// The parser's "UNKNOWN" category (title it couldn't read).
const UNKNOWN_STYLE: CategoryStyle = { label: "Unknown", color: "#9ca3af", opacity: 0.5, symbol: "D" };

function categoryStyle(category: string | null): CategoryStyle {
  const key = (category ?? "").trim().toLowerCase();
  return CATEGORY_STYLES.find(s => s.label.toLowerCase() === key) ?? UNKNOWN_STYLE;
}

const PAR_COLOR = "#facc15";
const FORECAST_COLOR = "#fdba74";

// PAGASA track-map symbol as inline SVG: a letter disc, or the cyclone swirl
// (filled for Super Typhoon, open for Severe Tropical Storm).
function symbolSvg(style: CategoryStyle, size: number): string {
  const fill = `fill="${style.color}" fill-opacity="${style.opacity}"`;
  if (style.symbol === "sty" || style.symbol === "sts") {
    const core = style.symbol === "sty"
      ? `<circle cx="12" cy="12" r="5.5" ${fill} stroke="#fff" stroke-width="1.5"/>`
      : `<circle cx="12" cy="12" r="5" fill="#111" fill-opacity="0.35" stroke="${style.color}" stroke-width="2.5"/>`;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24">`
      + `<path d="M12 6.5 C 15 2.5, 19 1.5, 22.5 2" fill="none" stroke="${style.color}" stroke-width="3" stroke-linecap="round"/>`
      + `<path d="M12 17.5 C 9 21.5, 5 22.5, 1.5 22" fill="none" stroke="${style.color}" stroke-width="3" stroke-linecap="round"/>`
      + core + `</svg>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24">`
    + `<circle cx="12" cy="12" r="10" ${fill} stroke="#fff" stroke-width="1.5"/>`
    + `<text x="12" y="16.2" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="#fff">${style.symbol}</text>`
    + `</svg>`;
}

// Kept small: bulletins are only a few hours apart, so 22px+ symbols piled
// on top of each other along the track.
function pointIcon(style: CategoryStyle, live: boolean): L.DivIcon {
  const size = live ? 18 : 14;
  // animate-ping ring marks the live typhoon's latest center.
  const ring = live
    ? `<span class="animate-ping absolute inset-0 rounded-full" style="background:${style.color};opacity:0.6"></span>`
    : "";
  return L.divIcon({
    html: `<span class="relative block" style="width:${size}px;height:${size}px">${ring}<span class="relative block">${symbolSvg(style, size)}</span></span>`,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function formatIssued(iso: string): string {
  return new Date(iso).toLocaleString("en-PH", {
    timeZone: "Asia/Manila", month: "short", day: "2-digit", hour: "numeric", minute: "2-digit",
  });
}

function bulletinLabel(p: TyphoonTrackPoint): string {
  return `TCB #${p.bulletin_count}${p.is_final ? "F" : ""}`;
}

function ParBadge({ inPar }: { inPar: boolean | null }) {
  if (inPar == null) {
    return <span className="inline-block rounded px-1.5 py-0.5 text-[9px] font-bold bg-muted text-muted-foreground">NO CENTER DATA</span>;
  }
  return inPar
    ? <span className="inline-block rounded px-1.5 py-0.5 text-[9px] font-bold bg-[#166534]/20 text-[#4ade80] border border-[#166534]">● INSIDE PAR</span>
    : <span className="inline-block rounded px-1.5 py-0.5 text-[9px] font-bold bg-[#7f1d1d]/20 text-[#f87171] border border-[#7f1d1d]">○ OUTSIDE PAR</span>;
}

interface TyphoonTrackLayerProps {
  tracks: TyphoonTrack[];
  // Fallback PAR outline when no track is loaded (e.g. no active typhoon),
  // so the overlay still shows the boundary.
  parPolygon: [number, number][];
}

// Map layers -- render inside <MapContainer>.
export function TyphoonTrackLayer({ tracks, parPolygon }: TyphoonTrackLayerProps) {
  const map = useMap();
  // tcb_id of the clicked bulletin; its radius circles get a bolder outline.
  // null = each track's latest bulletin.
  const [selectedTcbId, setSelectedTcbId] = useState<number | null>(null);

  const trackKey = tracks.map(t => t.typhoon_id).join(",");
  useEffect(() => {
    setSelectedTcbId(null);
    const latLngs: [number, number][] = [
      ...parPolygon,
      ...tracks.flatMap(t => [
        ...t.points.map(p => [p.lat, p.lng] as [number, number]),
        ...t.forecast.map(f => [f.lat, f.lon] as [number, number]),
      ]),
    ];
    if (latLngs.length > 0) map.fitBounds(L.latLngBounds(latLngs), { padding: [30, 30] });
    // Refit only when the set of typhoons shown changes, not on every refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackKey, map]);

  return (
    <>
      {parPolygon.length > 0 && (
        <Polygon
          positions={parPolygon}
          pathOptions={{ color: PAR_COLOR, weight: 2, dashArray: "8 6", fillOpacity: 0.02 }}
          interactive={false}
        />
      )}

      {tracks.map(track => {
        const points = track.points;
        const highlightId = selectedTcbId ?? points[points.length - 1]?.tcb_id;
        const last = points[points.length - 1];
        return (
          <Fragment key={track.typhoon_id}>
            {/* Wind circulation radius for every bulletin center -- strong-wind
                circles first so the storm-force circles draw on top. Fill
                only, no outline (2026-10-12); the selected bulletin's
                circles get a denser fill instead. */}
            {points.map(p => {
              if (p.wind_radius_km == null) return null;
              const s = categoryStyle(p.category);
              const sel = p.tcb_id === highlightId;
              return (
                <Circle
                  key={`strong-${p.tcb_id}`}
                  center={[p.lat, p.lng]}
                  radius={p.wind_radius_km * 1000}
                  interactive={false}
                  pathOptions={{ stroke: false, fillColor: s.color, fillOpacity: (sel ? 0.1 : 0.03) + 0.06 * s.opacity }}
                />
              );
            })}
            {points.map(p => {
              if (p.storm_force_radius_km == null) return null;
              const s = categoryStyle(p.category);
              const sel = p.tcb_id === highlightId;
              return (
                <Circle
                  key={`storm-${p.tcb_id}`}
                  center={[p.lat, p.lng]}
                  radius={p.storm_force_radius_km * 1000}
                  interactive={false}
                  pathOptions={{ stroke: false, fillColor: s.color, fillOpacity: (sel ? 0.16 : 0.08) + 0.14 * s.opacity }}
                />
              );
            })}

            {/* Observed track, each segment colored by the category at its start. */}
            {points.slice(1).map((p, i) => {
              const s = categoryStyle(points[i].category);
              return (
                <Polyline
                  key={`seg-${p.tcb_id}`}
                  positions={[[points[i].lat, points[i].lng], [p.lat, p.lng]]}
                  pathOptions={{ color: s.color, weight: 3.5, opacity: Math.max(s.opacity, 0.6) }}
                  interactive={false}
                />
              );
            })}

            {/* Forecast path from the latest bulletin only. */}
            {last && track.forecast.length > 0 && (
              <Polyline
                positions={[[last.lat, last.lng], ...track.forecast.map(f => [f.lat, f.lon] as [number, number])]}
                pathOptions={{ color: FORECAST_COLOR, weight: 3, dashArray: "2 8", lineCap: "round" }}
                interactive={false}
              />
            )}
            {track.forecast.map((f, i) => (
              <CircleMarker
                key={`fc-${i}`}
                center={[f.lat, f.lon]}
                radius={5}
                pathOptions={{ color: FORECAST_COLOR, weight: 2, fillColor: "#0b140d", fillOpacity: 1 }}
              >
                <Tooltip direction="right">{f.label} (forecast)</Tooltip>
                <Popup>
                  <div className="text-xs space-y-0.5">
                    <p className="font-semibold">{track.typhoon_name} — forecast</p>
                    <p>{f.label}</p>
                    {f.location && <p className="text-muted-foreground">{f.location}</p>}
                    <p>{f.lat.toFixed(1)}°N, {f.lon.toFixed(1)}°E</p>
                    <p>{f.inside_par ? "● Inside PAR" : "○ Outside PAR"}</p>
                  </div>
                </Popup>
              </CircleMarker>
            ))}

            {points.map(p => {
              const s = categoryStyle(p.category);
              const live = track.is_active && p.tcb_id === last?.tcb_id;
              return (
                <Marker
                  key={`pt-${p.tcb_id}`}
                  position={[p.lat, p.lng]}
                  icon={pointIcon(s, live)}
                  eventHandlers={{ click: () => setSelectedTcbId(p.tcb_id) }}
                >
                  <Tooltip direction="left">{bulletinLabel(p)} · {formatIssued(p.issued_at)}</Tooltip>
                  <Popup>
                    <div className="text-xs space-y-0.5">
                      <p className="font-semibold">{track.typhoon_name} — {bulletinLabel(p)}</p>
                      <p>{formatIssued(p.issued_at)}</p>
                      <p>{s.label} · {p.max_sustained_winds ?? "—"} km/h</p>
                      <p>{p.lat.toFixed(1)}°N, {p.lng.toFixed(1)}°E</p>
                      <p>Strong winds radius: {p.wind_radius_km != null ? `${p.wind_radius_km} km` : "—"}</p>
                      <p>Storm-force radius: {p.storm_force_radius_km != null ? `${p.storm_force_radius_km} km` : "—"}</p>
                      <p className="font-medium" style={{ color: p.inside_par ? "#16a34a" : "#dc2626" }}>
                        {p.inside_par ? "● Inside PAR" : "○ Outside PAR"}
                      </p>
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </Fragment>
        );
      })}
    </>
  );
}

function SymbolSwatch({ style }: { style: CategoryStyle }) {
  return <span className="inline-block shrink-0" dangerouslySetInnerHTML={{ __html: symbolSvg(style, 16) }} />;
}

interface TyphoonTrackLegendProps {
  tracks: TyphoonTrack[];
  loading: boolean;
  // Archived typhoon picked in the Farm Records filter, vs. the live one(s).
  archived: boolean;
}

// Legend -- render outside <MapContainer>, over the map.
export function TyphoonTrackLegend({ tracks, loading, archived }: TyphoonTrackLegendProps) {
  return (
    // Sits in GISLeafletMap's right-hand column under the overlay toggles;
    // min-h-0 lets it shrink and scroll instead of pushing past the map.
    <div className="pointer-events-auto bg-card/90 border border-border rounded-lg px-3 py-2 shadow-md w-[220px] min-h-0 overflow-y-auto">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Typhoon Track</p>

      {loading && <p className="text-[10px] text-muted-foreground mb-1.5">Loading track…</p>}
      {!loading && tracks.length === 0 && (
        <p className="text-[10px] text-muted-foreground mb-1.5">
          {archived ? "No bulletin data for this typhoon." : "No active typhoon right now."}
        </p>
      )}
      {tracks.map(t => (
        <div key={t.typhoon_id} className="mb-1.5">
          <p className="text-[11px] font-semibold leading-tight">
            {t.typhoon_name} {t.year}{" "}
            <span className="font-normal text-muted-foreground">({t.is_active ? "live" : "archived"}, {t.points.length} TCB{t.points.length === 1 ? "" : "s"})</span>
          </p>
          <ParBadge inPar={t.in_par} />
        </div>
      ))}

      <p className="text-[9px] uppercase tracking-wider text-muted-foreground mt-2 mb-1">Legend</p>
      <div className="space-y-0.5">
        {[...CATEGORY_STYLES].reverse().map(s => (
          <div key={s.label} className="flex items-center gap-1.5">
            <SymbolSwatch style={s} />
            <span className="text-[10px]">{s.label}</span>
          </div>
        ))}
        <div className="flex items-start gap-1.5 pt-1">
          <span className="w-4 h-4 rounded-full inline-block shrink-0" style={{ backgroundColor: "rgba(220,38,38,0.45)" }} />
          <span className="text-[10px] leading-tight">Area with at least storm-force winds (89 km/h, 48 kt or higher)</span>
        </div>
        <div className="flex items-start gap-1.5">
          <span className="w-4 h-4 rounded-full inline-block shrink-0" style={{ backgroundColor: "rgba(249,115,22,0.2)" }} />
          <span className="text-[10px] leading-tight">Area with at least strong winds (39 km/h, 22 kt or higher)</span>
        </div>
        <div className="flex items-center gap-1.5 pt-1">
          <span className="w-4 inline-block border-t-[3px]" style={{ borderColor: "#dc2626" }} />
          <span className="text-[10px]">Observed track</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 inline-block border-t-[3px] border-dotted" style={{ borderColor: FORECAST_COLOR }} />
          <span className="text-[10px]">Forecast (latest TCB)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-4 inline-block border-t-2 border-dashed" style={{ borderColor: PAR_COLOR }} />
          <span className="text-[10px]">PAR boundary</span>
        </div>
      </div>
      <p className="text-[9px] text-muted-foreground mt-1.5 leading-tight">Orange → red = weakest → strongest. Click a center to highlight its radius.</p>
    </div>
  );
}
