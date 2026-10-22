import { useCallback, useEffect, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, useMap, useMapEvents } from "react-leaflet";
import type { FeatureCollection } from "geojson";
import type { Layer, PathOptions } from "leaflet";
import "leaflet/dist/leaflet.css";
import { ChevronLeft, ChevronRight, Download, Lock, Map as MapIcon, Search, Table2, X } from "lucide-react";
import { toast } from "sonner";
import {
  ArchiveBatch, ArchiveExposureCollection, ArchiveFarmsCollection, ArchiveRecordsPage,
  downloadArchiveCsv, getArchiveExposure, getArchiveFarms, getArchiveRecords,
} from "@/lib/api";

// Read-only archive viewer (2026-10-22) -- everything here is read from the
// archive database through the backend's SELECT-only login. There are no edit
// controls anywhere, by design.

const PAGE_SIZE = 50;
const DEFAULT_CENTER: [number, number] = [8.38, 124.84]; // Region X

// Same TCWS palette as GISLeafletMap's signal dots.
const SIGNAL_COLORS: Record<number, string> = { 1: "#fde047", 2: "#f59e0b", 3: "#f97316", 4: "#ef4444", 5: "#991b1b" };

function payoutColor(total: number): string {
  if (total <= 0) return "#94a3b8";
  if (total < 5000) return "#86efac";
  if (total < 20000) return "#22c55e";
  return "#166534";
}

const peso = (v: number | null) => (v == null ? "—" : `₱${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`);

function RecordsTable({ archive }: { archive: ArchiveBatch }) {
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ArchiveRecordsPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => { setAppliedQuery(query); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setError(null);
    getArchiveRecords(archive.archive_id, appliedQuery, page, PAGE_SIZE)
      .then(res => setData(res.data))
      .catch(err => setError(err instanceof Error ? err.message : "Failed to load archived records."));
  }, [archive.archive_id, appliedQuery, page]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex items-center gap-2 mb-2">
        <div className="relative flex-1 max-w-sm">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search farmer, CIC no., municipality…"
            className="w-full border border-border rounded-lg pl-7 pr-3 py-1.5 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
          />
        </div>
        <span className="text-[10px] text-muted-foreground">{data ? `${data.total.toLocaleString()} rows` : "Loading…"}</span>
      </div>
      {error && <p className="text-[11px] text-red-600 mb-2">{error}</p>}
      <div className="overflow-auto border border-border rounded-lg flex-1 min-h-0">
        <table className="text-[11px] w-full">
          <thead className="sticky top-0">
            <tr className="bg-[#166534] text-white">
              {["Farmer", "Municipality", "Barangay", "CIC No.", "Area (ha)", "AC", "Typhoon", "TCWS", "Stage", "IF", "Payout"].map(h => (
                <th key={h} className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((r, i) => (
              <tr key={`${r.insurance_records_id}-${r.typhoon_name ?? ""}-${r.typhoon_year ?? ""}-${i}`} className="border-t border-border hover:bg-muted/30">
                <td className="px-2.5 py-1.5 whitespace-nowrap">{r.farmer_name || "—"}</td>
                <td className="px-2.5 py-1.5">{r.municipality ?? "—"}</td>
                <td className="px-2.5 py-1.5">{r.barangay ?? "—"}</td>
                <td className="px-2.5 py-1.5 font-mono">{r.policy_no ?? "—"}</td>
                <td className="px-2.5 py-1.5 text-right">{r.area_size ?? "—"}</td>
                <td className="px-2.5 py-1.5 text-right">{peso(r.amount_cover)}</td>
                <td className="px-2.5 py-1.5 whitespace-nowrap">{r.typhoon_name ? `${r.typhoon_name} ${r.typhoon_year}` : "—"}</td>
                <td className="px-2.5 py-1.5 text-center">{r.wind_signal ?? "—"}</td>
                <td className="px-2.5 py-1.5">{r.crop_stage ?? "—"}</td>
                <td className="px-2.5 py-1.5 text-right">{r.indemnity_factor ?? "—"}</td>
                <td className="px-2.5 py-1.5 text-right font-semibold">{peso(r.final_indemnity_payment)}</td>
              </tr>
            ))}
            {data && data.rows.length === 0 && (
              <tr><td colSpan={11} className="px-3 py-4 text-center text-muted-foreground">No matching records.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-end gap-2 mt-2 text-[11px]">
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="p-1 rounded border border-border disabled:opacity-40">
          <ChevronLeft size={12} />
        </button>
        <span>Page {page} of {pages}</span>
        <button onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page >= pages} className="p-1 rounded border border-border disabled:opacity-40">
          <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}

// Fits once to the archive's farm extent, then reloads farm polygons for the
// current viewport whenever the map stops moving.
function FarmLoader({ archiveId, onLoaded }: { archiveId: number; onLoaded: (fc: ArchiveFarmsCollection) => void }) {
  const map = useMap();
  const [fitted, setFitted] = useState(false);

  const load = useCallback(() => {
    const b = map.getBounds();
    getArchiveFarms(archiveId, fitted ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : undefined)
      .then(fc => {
        onLoaded(fc);
        if (!fitted) {
          setFitted(true);
          if (fc.extent) map.fitBounds([[fc.extent[1], fc.extent[0]], [fc.extent[3], fc.extent[2]]], { padding: [20, 20] });
        }
      })
      .catch(err => toast.error(err instanceof Error ? err.message : "Failed to load archived farms."));
  }, [archiveId, fitted, map, onLoaded]);

  useEffect(() => { if (!fitted) load(); }, [fitted, load]);
  useMapEvents({ moveend: () => { if (fitted) load(); } });
  return null;
}

function ArchiveMap({ archive }: { archive: ArchiveBatch }) {
  const [farms, setFarms] = useState<ArchiveFarmsCollection | null>(null);
  const [exposure, setExposure] = useState<ArchiveExposureCollection | null>(null);
  // GeoJSON layers only read `data` on mount -- bump the key to redraw.
  const [farmsVersion, setFarmsVersion] = useState(0);

  useEffect(() => {
    getArchiveExposure(archive.archive_id)
      .then(setExposure)
      .catch(err => toast.error(err instanceof Error ? err.message : "Failed to load typhoon areas."));
  }, [archive.archive_id]);

  const handleFarms = useCallback((fc: ArchiveFarmsCollection) => {
    setFarms(fc);
    setFarmsVersion(v => v + 1);
  }, []);

  const exposureStyle = (feature?: { properties?: { kind?: string; max_signal_level?: number } }): PathOptions => {
    if (feature?.properties?.kind === "track") return { color: "#ff5200", weight: 2, dashArray: "6, 4" };
    const color = SIGNAL_COLORS[feature?.properties?.max_signal_level ?? 0] ?? "#f59e0b";
    return { color, weight: 1, fillColor: color, fillOpacity: 0.15 };
  };

  const onExposureFeature = (feature: { properties: Record<string, unknown> }, layer: Layer) => {
    const p = feature.properties;
    layer.bindTooltip(
      p.kind === "track"
        ? `${p.typhoon_name} ${p.typhoon_year} track`
        : `${p.municipality}, ${p.province} — TCWS ${p.max_signal_level}, ${p.total_exposure_hours}h (${p.typhoon_name} ${p.typhoon_year})`,
      { sticky: true },
    );
  };

  const onFarmFeature = (feature: { properties: Record<string, unknown> }, layer: Layer) => {
    const p = feature.properties;
    layer.bindPopup(
      `<div style="font-size:11px"><b>${p.farmer_name || "Unknown farmer"}</b><br/>` +
      `Farm ${p.csv_farm_reference ?? p.farm_id} · ${p.barangay ?? ""}, ${p.municipality ?? ""}<br/>` +
      `Area: ${p.area_size ?? "—"} ha<br/>Total payout: ₱${Number(p.total_payout).toLocaleString()}</div>`,
    );
  };

  return (
    <div className="relative flex-1 min-h-[420px] rounded-lg overflow-hidden border border-border">
      <MapContainer center={DEFAULT_CENTER} zoom={9} className="h-full w-full" style={{ minHeight: 420 }}>
        <TileLayer
          attribution='Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener noreferrer">Esri</a> — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        />
        {exposure && (
          <GeoJSON
            key={`exposure-${archive.archive_id}`}
            data={exposure as unknown as FeatureCollection}
            style={exposureStyle as never}
            onEachFeature={onExposureFeature as never}
          />
        )}
        {farms && (
          <GeoJSON
            key={`farms-${archive.archive_id}-${farmsVersion}`}
            data={farms as unknown as FeatureCollection}
            style={((f?: { properties?: { total_payout?: number } }) => {
              const color = payoutColor(f?.properties?.total_payout ?? 0);
              return { color, weight: 1, fillColor: color, fillOpacity: 0.5 };
            }) as never}
            onEachFeature={onFarmFeature as never}
          />
        )}
        <FarmLoader archiveId={archive.archive_id} onLoaded={handleFarms} />
      </MapContainer>

      <div className="absolute bottom-3 left-3 z-[1000] bg-card/95 border border-border rounded-lg p-2.5 text-[10px] space-y-1 shadow">
        <p className="font-semibold">Farm payout</p>
        {[["#94a3b8", "No payout"], ["#86efac", "< ₱5,000"], ["#22c55e", "₱5,000–20,000"], ["#166534", "≥ ₱20,000"]].map(([c, l]) => (
          <p key={l} className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: c }} />{l}</p>
        ))}
        <p className="font-semibold pt-1">Exposure area (TCWS)</p>
        <p className="flex items-center gap-1.5">
          {[1, 2, 3, 4, 5].map(s => <span key={s} className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: SIGNAL_COLORS[s] }} title={`Signal ${s}`} />)}
          <span>1 → 5</span>
        </p>
      </div>
      {farms?.truncated && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-amber-50 border border-amber-300 text-amber-800 text-[10px] rounded-lg px-3 py-1.5 shadow">
          Showing the first 5,000 farms in view — zoom in to see the rest.
        </div>
      )}
    </div>
  );
}

interface ArchiveViewerProps {
  archive: ArchiveBatch;
  onClose: () => void;
}

export function ArchiveViewer({ archive, onClose }: ArchiveViewerProps) {
  const [mode, setMode] = useState<"table" | "map">("table");
  const [downloading, setDownloading] = useState(false);

  const handleCsv = () => {
    setDownloading(true);
    downloadArchiveCsv(archive.archive_id)
      .catch(err => toast.error(err instanceof Error ? err.message : "Download failed."))
      .finally(() => setDownloading(false));
  };

  return (
    <div className="bg-card border border-border rounded-xl p-4 flex flex-col" style={{ height: "calc(100vh - 140px)", minHeight: 560 }}>
      <div className="flex items-center justify-between gap-2 mb-3">
        <div>
          <p className="text-sm font-semibold flex items-center gap-2">
            View archive: {archive.label}
            <span className="flex items-center gap-1 text-[10px] font-normal text-muted-foreground px-2 py-0.5 rounded-full border border-border">
              <Lock size={9} /> Read-only
            </span>
          </p>
          <p className="text-[10px] text-muted-foreground">
            Archive #{archive.archive_id} · archived {new Date(archive.archived_at).toLocaleString()} by {archive.archived_by_name ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border overflow-hidden text-[11px]">
            <button onClick={() => setMode("table")} className={`flex items-center gap-1 px-2.5 py-1.5 ${mode === "table" ? "bg-[#166534] text-white" : "hover:bg-muted"}`}>
              <Table2 size={12} /> Table
            </button>
            <button onClick={() => setMode("map")} className={`flex items-center gap-1 px-2.5 py-1.5 ${mode === "map" ? "bg-[#166534] text-white" : "hover:bg-muted"}`}>
              <MapIcon size={12} /> Map
            </button>
          </div>
          <button onClick={handleCsv} disabled={downloading} className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-border text-[11px] hover:bg-muted disabled:opacity-50">
            <Download size={12} /> CSV
          </button>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground" title="Close">
            <X size={14} />
          </button>
        </div>
      </div>
      {mode === "table" ? <RecordsTable archive={archive} /> : <ArchiveMap archive={archive} />}
    </div>
  );
}
