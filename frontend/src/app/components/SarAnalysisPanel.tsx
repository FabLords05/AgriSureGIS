import { Satellite, X, MapPin, Calendar, BarChart2, Info, CheckCircle2, AlertTriangle, Layers, Database } from "lucide-react";
import type { SarLayer, PlantedCheckSummary } from "@/lib/api";
import { PLANTED_CHECK_COLORS } from "./GISLeafletMap";

// "Verify Farm Planted" panel (2026-10-12) -- slides in over the Spatial
// Analysis map, following ui-prototype's AOISARPanel shell (form ->
// processing -> results). AOI fixed to the "Affected by" typhoon's farms (all bulletins).
//
// Phase 2 (2026-10-12, per Cristian): the main action is the automatic
// planted check -- every affected farm GREEN (planted, no field visit) or
// YELLOW (needs field verification), per docs/SAR_ISPLANTED_METHOD.md §3.
// Results are stored per typhoon, so reopening shows them without a re-run.
// The Phase 1 pre-event VV/VH colour layer stays as an optional overlay.
interface SarAnalysisPanelProps {
  darkMode: boolean;
  // e.g. "OPONG 2026" -- the "Affected by" typhoon.
  typhoonLabel: string;
  summary: PlantedCheckSummary | null;
  checkLoading: boolean;
  checkError: string | null;
  onRunCheck: () => void;
  layer: SarLayer | null;
  layerLoading: boolean;
  layerError: string | null;
  onClose: () => void;
  layerVisible: boolean;
  onLayerVisibleChange: (visible: boolean) => void;
  opacity: number;
  onOpacityChange: (opacity: number) => void;
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-100">
      <AlertTriangle size={11} className="text-red-500 shrink-0 mt-0.5" />
      <p className="text-[10px] text-red-600">{message}</p>
    </div>
  );
}

export function SarAnalysisPanel({
  darkMode, typhoonLabel, summary, checkLoading, checkError, onRunCheck,
  layer, layerLoading, layerError, onClose,
  layerVisible, onLayerVisibleChange, opacity, onOpacityChange,
}: SarAnalysisPanelProps) {
  const step = checkLoading ? "processing" : summary ? "results" : "form";

  // The optional colour overlay -- the same controls in both form and results.
  const layerControls = (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-[11px] cursor-pointer select-none">
        <input type="checkbox" checked={layerVisible} onChange={e => onLayerVisibleChange(e.target.checked)} />
        Show radar colour layer (VV/VH)
        {layerLoading && <span className="text-[10px] text-muted-foreground">Loading…</span>}
      </label>
      {layerError && <ErrorNote message={layerError} />}
      {layer && layerVisible && (
        <>
          <div className="border border-border rounded-lg overflow-hidden">
            <div className="px-3 py-2 bg-muted/40 border-b border-border flex items-center gap-1.5">
              <Layers size={11} className="text-[#166534]" />
              <p className="text-[11px] font-semibold">VV/VH Ratio (dB)</p>
              <span className="text-[9px] text-muted-foreground ml-auto">{layer.window_start} → {layer.window_end}</span>
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
          <label className="block text-[11px]">
            <span className="text-muted-foreground">Opacity {Math.round(opacity * 100)}%</span>
            <input
              type="range" min={0.2} max={1} step={0.05} value={opacity}
              onChange={e => onOpacityChange(Number(e.target.value))}
              className="w-full"
            />
          </label>
        </>
      )}
    </div>
  );

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
                Farms affected by {typhoonLabel}
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Every farm under TCWS signal 2+ in any of its bulletins (the "Affected by" set).
                </p>
              </div>
            </div>

            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <Calendar size={11} /> Imagery Window
              </p>
              <div className="border border-border rounded-lg px-3 py-2 text-[11px]">
                The 150 days before {typhoonLabel}'s first bulletin
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Before the storm only. Long enough to see the field flooded, then the crop growing.
                </p>
              </div>
            </div>

            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <BarChart2 size={11} /> Rule
              </p>
              <div className="border border-border rounded-lg px-3 py-2 text-[11px]">
                Green only if all 5 conditions pass
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Flood low point · biomass rise · canopy closure · VV/VH agree · planting-window timing
                  (Gutierrez et al. 2019; Villano et al. 2019)
                </p>
              </div>
            </div>

            <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-100">
              <Info size={11} className="text-blue-500 shrink-0 mt-0.5" />
              <p className="text-[10px] text-blue-600">
                Each farm comes back green (planted, no field visit) or yellow (needs field verification).
                Radar readings are saved, so running it again only asks Google Earth Engine for what's missing.
                The result does not change the assessment or the PABS export.
              </p>
            </div>

            {checkError && <ErrorNote message={checkError} />}

            <button
              onClick={onRunCheck}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#166534] hover:bg-[#14532d] text-white text-sm font-bold transition-all shadow-lg shadow-[#166534]/25"
            >
              <Satellite size={15} /> Run Planted Check
            </button>

            {layerControls}
          </div>
        )}

        {step === "processing" && (
          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
            <div className="w-16 h-16 rounded-full border-4 border-[#166534]/20 border-t-[#166534] animate-spin mb-6" />
            <p className="text-sm font-bold mb-2">Running Planted Check</p>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Reading saved radar data and fetching anything missing from Google Earth Engine.
              A first run on a large typhoon can take a few minutes.
            </p>
          </div>
        )}

        {step === "results" && summary && (
          <div className="p-4 space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle2 size={14} className="text-emerald-500" />
              <p className="text-xs font-bold">Planted Check Complete</p>
              <span className="text-[10px] text-muted-foreground ml-auto">{summary.window_start} → {summary.window_end}</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "Checked", value: summary.checked, color: undefined },
                { label: "Green", value: summary.planted, color: PLANTED_CHECK_COLORS.planted },
                { label: "Yellow", value: summary.field_verify, color: PLANTED_CHECK_COLORS.field_verify },
              ].map(s => (
                <div key={s.label} className="bg-card border border-border rounded-lg p-2.5 text-center">
                  <p className="text-[9px] text-muted-foreground">{s.label}</p>
                  <p className="text-lg font-black mt-0.5" style={{ color: s.color }}>{s.value}</p>
                </div>
              ))}
            </div>

            {summary.reasons.length > 0 && (
              <div className="border border-border rounded-lg overflow-hidden">
                <div className="px-3 py-2 bg-muted/40 border-b border-border">
                  <p className="text-[11px] font-semibold">Why yellow</p>
                </div>
                <div className="p-3 space-y-1">
                  {summary.reasons.map(r => (
                    <div key={r.code} className="flex justify-between text-[10.5px]">
                      <span>{r.label}</span>
                      <span className="font-mono text-muted-foreground">{r.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <p className="text-[10px] text-muted-foreground flex items-start gap-1.5">
              <Database size={10} className="shrink-0 mt-0.5" />
              <span>
                {summary.fetched_from_gee != null
                  ? `${summary.fetched_from_gee} farm(s) fetched from Google Earth Engine, ${summary.from_cache ?? 0} read from saved data.`
                  : "Saved result."}
                {summary.checked_at && ` Checked ${new Date(summary.checked_at).toLocaleString()}.`}
              </span>
            </p>

            {checkError && <ErrorNote message={checkError} />}

            {layerControls}

            <button
              onClick={onRunCheck}
              className="w-full py-2 rounded-lg border border-[#166534] text-[#166534] text-[11px] font-medium hover:bg-[#166534]/10 transition-colors"
            >
              Re-run planted check
            </button>
            <p className="text-[10px] text-muted-foreground">
              Recorded only. Does not change the assessment or the PABS export.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
