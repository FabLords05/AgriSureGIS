import { Satellite, X, MapPin, Calendar, BarChart2, Info, CheckCircle2, AlertTriangle, Layers } from "lucide-react";
import type { Bulletin, SarLayer } from "@/lib/api";

// "Verify Farm Planted" panel (2026-10-12) -- slides in over the Spatial
// Analysis map, following ui-prototype's AOISARPanel shell (form ->
// processing -> results) but trimmed to Phase 1 of
// docs/SAR_ISPLANTED_METHOD.md: planted-area only, AOI fixed to the
// "Affected Only" farms, a real pre-event Sentinel-1 VV/VH layer from
// Google Earth Engine (no simulated progress, no per-farm percentages --
// those are Phase 2). The Specialist reads the colour and records the
// verdict per farm from the map's Farm Details panel.
interface SarAnalysisPanelProps {
  darkMode: boolean;
  bulletin: Bulletin;
  layer: SarLayer | null;
  loading: boolean;
  error: string | null;
  onRun: () => void;
  onClose: () => void;
  layerVisible: boolean;
  onLayerVisibleChange: (visible: boolean) => void;
  opacity: number;
  onOpacityChange: (opacity: number) => void;
}

export function SarAnalysisPanel({
  darkMode, bulletin, layer, loading, error, onRun, onClose,
  layerVisible, onLayerVisibleChange, opacity, onOpacityChange,
}: SarAnalysisPanelProps) {
  const step = loading ? "processing" : layer ? "results" : "form";

  return (
    <div
      className="absolute inset-y-0 right-0 z-[1100] flex flex-col shadow-2xl border-l border-border"
      style={{ width: 380, background: darkMode ? "#111e11" : "#ffffff" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0 border-b border-border"
        style={{ background: darkMode ? "#192e19" : "#166534" }}
      >
        <div className="flex items-center gap-2.5">
          <Satellite size={16} className="text-white" />
          <div>
            <p className="text-white text-xs font-bold">SAR Analysis — Area of Interest</p>
            <p className="text-white/60 text-[9px]">Google Earth Engine · Sentinel-1 C-Band</p>
          </div>
        </div>
        <button onClick={onClose} className="text-white/60 hover:text-white transition-colors">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        {step === "form" && (
          <div className="p-4 space-y-4">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <MapPin size={11} /> Area of Interest
              </p>
              <div className="border border-border rounded-lg px-3 py-2 text-[11px]">
                Affected farms — {bulletin.typhoon_name} bulletin #{bulletin.bulletin_count}
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Farms with a GPX boundary inside TCWS signal 2+ areas (the "Affected Only" set).
                </p>
              </div>
            </div>

            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <Calendar size={11} /> Imagery Window
              </p>
              <div className="border border-border rounded-lg px-3 py-2 text-[11px]">
                Pre-event: the 24 days before {bulletin.typhoon_name}'s first bulletin
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Before the storm only — a post-event image can't tell "never planted" from "flattened".
                </p>
              </div>
            </div>

            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <BarChart2 size={11} /> Analysis Type
              </p>
              <div className="border border-border rounded-lg px-3 py-2 text-[11px]">
                Planted Area Detection (VV/VH Backscatter)
              </div>
            </div>

            <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-100">
              <Info size={11} className="text-blue-500 shrink-0 mt-0.5" />
              <p className="text-[10px] text-blue-600">
                The layer colours each affected polygon by its Sentinel-1 VV/VH ratio. Check the colour,
                then record Planted / Not planted from the farm's details on the map. The verdict is
                recorded only — it does not change the assessment or the PABS export.
              </p>
            </div>

            {error && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-100">
                <AlertTriangle size={11} className="text-red-500 shrink-0 mt-0.5" />
                <p className="text-[10px] text-red-600">{error}</p>
              </div>
            )}

            <button
              onClick={onRun}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#166534] hover:bg-[#14532d] text-white text-sm font-bold transition-all shadow-lg shadow-[#166534]/25"
            >
              <Satellite size={15} /> Submit SAR Request to GEE
            </button>
          </div>
        )}

        {step === "processing" && (
          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
            <div className="w-16 h-16 rounded-full border-4 border-[#166534]/20 border-t-[#166534] animate-spin mb-6" />
            <p className="text-sm font-bold mb-2">Running SAR Analysis</p>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Building the pre-event Sentinel-1 composite in Google Earth Engine…
            </p>
          </div>
        )}

        {step === "results" && layer && (
          <div className="p-4 space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle2 size={14} className="text-emerald-500" />
              <p className="text-xs font-bold">SAR Layer Ready</p>
              <span className="text-[10px] text-muted-foreground ml-auto">{layer.window_start} → {layer.window_end}</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "Farms", value: String(layer.farm_count) },
                { label: "Scenes", value: String(layer.scene_dates.length) },
                { label: "Orbit", value: `#${layer.relative_orbit}` },
              ].map(s => (
                <div key={s.label} className="bg-card border border-border rounded-lg p-2.5 text-center">
                  <p className="text-[9px] text-muted-foreground">{s.label}</p>
                  <p className="text-lg font-black mt-0.5 text-[#166534]">{s.value}</p>
                </div>
              ))}
            </div>

            <p className="text-[10px] text-muted-foreground">
              Scene dates: {layer.scene_dates.join(", ")} · descending pass
            </p>
            {layer.capped && (
              <p className="text-[10px] text-amber-600">
                Only the first {layer.farm_count} affected farms were sent to Earth Engine (request size limit).
              </p>
            )}
            {layer.skipped_no_geom > 0 && (
              <p className="text-[10px] text-muted-foreground">
                {layer.skipped_no_geom} affected farm(s) have no GPX boundary and can't be checked.
              </p>
            )}

            {/* Colour legend -- same stretch the backend renders with. */}
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-muted/40 border-b border-border flex items-center gap-1.5">
                <Layers size={11} className="text-[#166534]" />
                <p className="text-[11px] font-semibold">VV/VH Ratio (dB)</p>
              </div>
              <div className="p-3">
                <div className="h-3 rounded" style={{ background: `linear-gradient(to right, ${layer.palette.join(", ")})` }} />
                <div className="flex justify-between text-[9px] text-muted-foreground mt-1">
                  <span>{layer.min_db} · canopy closed</span>
                  <span>planted</span>
                  <span>sparse</span>
                  <span>{layer.max_db}+ · bare / flooded</span>
                </div>
              </div>
            </div>

            <label className="flex items-center gap-2 text-[11px] cursor-pointer select-none">
              <input type="checkbox" checked={layerVisible} onChange={e => onLayerVisibleChange(e.target.checked)} />
              Show SAR layer on the map
            </label>
            <label className="block text-[11px]">
              <span className="text-muted-foreground">Opacity {Math.round(opacity * 100)}%</span>
              <input
                type="range" min={0.2} max={1} step={0.05} value={opacity}
                onChange={e => onOpacityChange(Number(e.target.value))}
                className="w-full"
              />
            </label>

            <button
              onClick={onRun}
              className="w-full py-2 rounded-lg border border-[#166534] text-[#166534] text-[11px] font-medium hover:bg-[#166534]/10 transition-colors"
            >
              Re-run for this bulletin
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
