import { useState } from "react";
import {
  Satellite, X, ChevronDown, CheckCircle2, Loader, AlertTriangle,
  MapPin, Calendar, Layers, BarChart2, Download, Info
} from "lucide-react";
import { mockFarmers } from "./mockData";

interface SARResult {
  farmId: string;
  farmerName: string;
  municipality: string;
  areaHa: number;
  sarPlantedPct: number;
  sarFloodedPct: number;
  ndviIndex: number;
  status: "healthy" | "damaged" | "flooded" | "unplanted";
}

const MOCK_SAR_RESULTS: SARResult[] = mockFarmers.map(f => {
  const baseHealth = f.signalNo === 3 ? 0.35 : f.signalNo === 2 ? 0.65 : 0.88;
  const rand = (seed: number) => ((seed * 9301 + 49297) % 233280) / 233280;
  const r = rand(f.rowId * 17);
  const sarPlantedPct = f.planted ? Math.round((baseHealth + r * 0.2 - 0.1) * 100) : Math.round(r * 15);
  const sarFloodedPct = f.signalNo === 3 ? Math.round((0.4 + r * 0.35) * 100) : f.signalNo === 2 ? Math.round((0.15 + r * 0.25) * 100) : Math.round(r * 12 * 100) / 100;
  const ndviIndex = f.planted ? parseFloat((0.3 + r * 0.5 - (f.signalNo - 1) * 0.12).toFixed(2)) : parseFloat((0.05 + r * 0.1).toFixed(2));
  const status: SARResult["status"] = !f.planted ? "unplanted"
    : sarFloodedPct > 60 ? "flooded"
    : ndviIndex < 0.25 ? "damaged"
    : "healthy";
  return {
    farmId: f.farmId,
    farmerName: f.insuredName,
    municipality: f.municipality,
    areaHa: f.areaHectare,
    sarPlantedPct: Math.min(98, Math.max(0, sarPlantedPct)),
    sarFloodedPct: Math.min(95, Math.max(0, sarFloodedPct)),
    ndviIndex: Math.min(0.85, Math.max(0.02, ndviIndex)),
    status,
  };
});

const STATUS_STYLE: Record<SARResult["status"], { label: string; cls: string }> = {
  healthy:   { label: "Healthy",   cls: "bg-emerald-100 text-emerald-700" },
  damaged:   { label: "Damaged",   cls: "bg-amber-100 text-amber-700"     },
  flooded:   { label: "Flooded",   cls: "bg-red-100 text-red-700"          },
  unplanted: { label: "Unplanted", cls: "bg-gray-100 text-gray-500"        },
};

interface AOISARPanelProps {
  onClose: () => void;
  geeProjectId: string;
  darkMode: boolean;
}

export function AOISARPanel({ onClose, geeProjectId, darkMode }: AOISARPanelProps) {
  const [step, setStep]         = useState<"form" | "processing" | "results">("form");
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("");
  const [dateFrom, setDateFrom] = useState("2024-10-25");
  const [dateTo, setDateTo]     = useState("2024-11-05");
  const [analysisType, setAnalysisType] = useState("planted_area");
  const [satellite, setSatellite]       = useState("sentinel1");
  const [aoiMode, setAoiMode]           = useState<"province" | "municipality">("province");
  const [filterMuni, setFilterMuni]     = useState("All");

  const MUNICIPALITIES = ["All","Naga City","Pili","Libmanan","Sipocot","Goa","Lagonoy"];

  const handleSubmit = () => {
    setStep("processing");
    setProgress(0);

    const steps = [
      { pct: 12,  msg: "Authenticating with Google Earth Engine…"       },
      { pct: 28,  msg: "Fetching Sentinel-1 SAR tiles for AOI…"         },
      { pct: 44,  msg: "Applying speckle filter and terrain correction…" },
      { pct: 60,  msg: "Computing backscatter coefficients (VV/VH)…"    },
      { pct: 74,  msg: "Classifying flooded vs. planted areas…"         },
      { pct: 88,  msg: "Calculating NDVI indices per farm polygon…"      },
      { pct: 96,  msg: "Compiling per-polygon SAR results…"             },
      { pct: 100, msg: "Analysis complete."                              },
    ];

    let i = 0;
    const tick = setInterval(() => {
      if (i < steps.length) {
        setProgress(steps[i].pct);
        setProgressMsg(steps[i].msg);
        i++;
      } else {
        clearInterval(tick);
        setTimeout(() => setStep("results"), 400);
      }
    }, 350);
  };

  const filteredResults = filterMuni === "All"
    ? MOCK_SAR_RESULTS
    : MOCK_SAR_RESULTS.filter(r => r.municipality === filterMuni);

  const summary = {
    avgPlanted: Math.round(MOCK_SAR_RESULTS.filter(r=>r.sarPlantedPct>0).reduce((s,r)=>s+r.sarPlantedPct,0)/MOCK_SAR_RESULTS.filter(r=>r.sarPlantedPct>0).length),
    avgFlooded: Math.round(MOCK_SAR_RESULTS.reduce((s,r)=>s+r.sarFloodedPct,0)/MOCK_SAR_RESULTS.length),
    avgNdvi:    (MOCK_SAR_RESULTS.reduce((s,r)=>s+r.ndviIndex,0)/MOCK_SAR_RESULTS.length).toFixed(2),
    flooded:    MOCK_SAR_RESULTS.filter(r=>r.status==="flooded").length,
    damaged:    MOCK_SAR_RESULTS.filter(r=>r.status==="damaged").length,
  };

  return (
    <div
      className="absolute inset-y-0 right-0 z-30 flex flex-col shadow-2xl border-l border-border"
      style={{ width: step === "results" ? 520 : 380, background: darkMode ? "#111e11" : "#ffffff" }}
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

      {/* Content */}
      <div className="flex-1 overflow-auto">

        {/* ── FORM STEP ── */}
        {step === "form" && (
          <div className="p-4 space-y-4">
            {/* AOI Definition */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <MapPin size={11} /> Area of Interest
              </p>
              <div className="grid grid-cols-2 gap-2 mb-2">
                {(["province","municipality"] as const).map(m => (
                  <button
                    key={m}
                    onClick={() => setAoiMode(m)}
                    className={`py-2 rounded-lg border text-[11px] font-medium transition-all ${aoiMode===m ? "border-[#166534] bg-[#166534]/8 text-[#166534]" : "border-border text-muted-foreground hover:border-[#166534]/40"}`}
                  >
                    {m === "province" ? "Whole Province" : "By Municipality"}
                  </button>
                ))}
              </div>

              {aoiMode === "municipality" && (
                <select
                  value={filterMuni}
                  onChange={e => setFilterMuni(e.target.value)}
                  className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                >
                  {MUNICIPALITIES.map(m => <option key={m}>{m}</option>)}
                </select>
              )}

              <div className="mt-2 p-2.5 rounded-lg border border-border bg-muted/30 space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-muted-foreground">Province:</span>
                  <span className="font-medium">Camarines Sur, Philippines</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-muted-foreground">Bounding Box (N):</span>
                  <span className="font-mono">13.8922° N</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-muted-foreground">Bounding Box (S):</span>
                  <span className="font-mono">13.1445° N</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-muted-foreground">Bounding Box (E/W):</span>
                  <span className="font-mono">123.1°E – 123.9°E</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-muted-foreground">Farm Polygons:</span>
                  <span className="font-medium text-[#166534]">20 polygons loaded</span>
                </div>
              </div>
            </div>

            {/* GEE Configuration */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <Layers size={11} /> GEE Configuration
              </p>
              <div className="space-y-2">
                <div>
                  <label className="text-[10px] text-muted-foreground block mb-1">GCP Project ID</label>
                  <input
                    value={geeProjectId}
                    readOnly
                    className="w-full border border-border rounded-lg px-3 py-1.5 text-[11px] bg-muted/30 font-mono"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground block mb-1">Satellite / Dataset</label>
                  <select
                    value={satellite}
                    onChange={e => setSatellite(e.target.value)}
                    className="w-full border border-border rounded-lg px-3 py-1.5 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  >
                    <option value="sentinel1">Sentinel-1 SAR (C-Band, GRD)</option>
                    <option value="sentinel2">Sentinel-2 Multispectral</option>
                    <option value="landsat8">Landsat-8 OLI</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Date Range */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <Calendar size={11} /> Date Range
              </p>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-muted-foreground block mb-1">Start Date</label>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={e => setDateFrom(e.target.value)}
                    className="w-full border border-border rounded-lg px-3 py-1.5 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-muted-foreground block mb-1">End Date</label>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={e => setDateTo(e.target.value)}
                    className="w-full border border-border rounded-lg px-3 py-1.5 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  />
                </div>
              </div>
            </div>

            {/* Analysis Type */}
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1.5">
                <BarChart2 size={11} /> Analysis Type
              </p>
              <select
                value={analysisType}
                onChange={e => setAnalysisType(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              >
                <option value="planted_area">Planted Area Detection (VV/VH Backscatter)</option>
                <option value="flood_extent">Flood Extent Mapping</option>
                <option value="crop_health">Crop Health Index (NDVI/EVI)</option>
                <option value="combined">Combined — Planted Area + Flood + NDVI</option>
              </select>
            </div>

            {/* Info Banner */}
            <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-100">
              <Info size={11} className="text-blue-500 shrink-0 mt-0.5" />
              <p className="text-[10px] text-blue-600">
                SAR analysis cross-references farm polygon boundaries with Sentinel-1 imagery to determine the percentage of planted area within each polygon. Results are used to validate indemnity calculations.
              </p>
            </div>

            {/* Submit */}
            <button
              onClick={handleSubmit}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#166534] hover:bg-[#14532d] text-white text-sm font-bold transition-all shadow-lg shadow-[#166534]/25"
            >
              <Satellite size={15} /> Submit SAR Request to GEE
            </button>
          </div>
        )}

        {/* ── PROCESSING STEP ── */}
        {step === "processing" && (
          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
            <div className="w-16 h-16 rounded-full border-4 border-[#166534]/20 border-t-[#166534] animate-spin mb-6" />
            <p className="text-sm font-bold mb-2">Running SAR Analysis</p>
            <p className="text-[11px] text-muted-foreground mb-6 leading-relaxed">{progressMsg}</p>
            <div className="w-full bg-muted rounded-full h-2 mb-2">
              <div
                className="h-2 rounded-full bg-[#166534] transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground">{progress}% complete</p>
            <div className="mt-6 text-left space-y-1.5 w-full">
              {[
                "GEE Project: " + geeProjectId,
                "Dataset: Sentinel-1 SAR (C-Band GRD)",
                `Period: ${dateFrom} → ${dateTo}`,
                "Polygons: 20 farm boundaries",
                "Orbit: Ascending + Descending passes",
              ].map((t, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#166534]/50 shrink-0" />
                  {t}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── RESULTS STEP ── */}
        {step === "results" && (
          <div className="p-4 space-y-3">
            {/* Summary Cards */}
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle2 size={14} className="text-emerald-500" />
              <p className="text-xs font-bold">SAR Analysis Complete</p>
              <span className="text-[10px] text-muted-foreground ml-auto">{dateFrom} → {dateTo}</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label:"Avg. Planted", value:`${summary.avgPlanted}%`, color:"#166534" },
                { label:"Avg. Flooded", value:`${summary.avgFlooded}%`, color:"#ef4444" },
                { label:"Avg. NDVI",    value:summary.avgNdvi,          color:"#ca8a04" },
              ].map((s,i) => (
                <div key={i} className="bg-card border border-border rounded-lg p-2.5 text-center">
                  <p className="text-[9px] text-muted-foreground">{s.label}</p>
                  <p className="text-lg font-black mt-0.5" style={{ color: s.color }}>{s.value}</p>
                </div>
              ))}
            </div>

            {/* Status summary */}
            <div className="grid grid-cols-2 gap-2">
              {[
                { label:`${summary.flooded} Flooded Farms`,  cls:"bg-red-50 border-red-100 text-red-700"     },
                { label:`${summary.damaged} Damaged Farms`,  cls:"bg-amber-50 border-amber-100 text-amber-700"},
              ].map((s,i) => (
                <div key={i} className={`p-2 rounded-lg border text-center text-[10px] font-semibold ${s.cls}`}>
                  <AlertTriangle size={11} className="mx-auto mb-0.5" />
                  {s.label}
                </div>
              ))}
            </div>

            {/* Mock SAR Heatmap visualization */}
            <div className="border border-border rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-muted/40 border-b border-border flex items-center gap-1.5">
                <Satellite size={11} className="text-[#166534]" />
                <p className="text-[11px] font-semibold">SAR Backscatter Composite (False Color)</p>
              </div>
              <canvas
                width={480}
                height={140}
                className="w-full"
                ref={canvas => {
                  if (!canvas) return;
                  const ctx = canvas.getContext("2d");
                  if (!ctx) return;
                  // Background — ocean / land
                  const grad = ctx.createLinearGradient(0, 0, 480, 140);
                  grad.addColorStop(0,   "#1a3a5f");
                  grad.addColorStop(0.5, "#2d5a3d");
                  grad.addColorStop(1,   "#1a2e1a");
                  ctx.fillStyle = grad;
                  ctx.fillRect(0, 0, 480, 140);
                  // SAR farm patches
                  MOCK_SAR_RESULTS.forEach((r, i) => {
                    const cols = 5;
                    const cx = 40 + (i % cols) * 88;
                    const cy = 30 + Math.floor(i / cols) * 45;
                    const health = r.ndviIndex;
                    const flood  = r.sarFloodedPct / 100;
                    const g = Math.round(100 + health * 120);
                    const b = Math.round(flood * 200);
                    ctx.fillStyle = `rgba(${50},${g},${b},0.85)`;
                    ctx.fillRect(cx - 18, cy - 12, 36, 22);
                    ctx.strokeStyle = "rgba(255,255,255,0.2)";
                    ctx.lineWidth = 0.5;
                    ctx.strokeRect(cx - 18, cy - 12, 36, 22);
                    ctx.font = "bold 8px sans-serif";
                    ctx.fillStyle = "rgba(255,255,255,0.9)";
                    ctx.textAlign = "center";
                    ctx.fillText(r.farmId, cx, cy + 4);
                  });
                  // Legend
                  const lg = ctx.createLinearGradient(10, 125, 140, 125);
                  lg.addColorStop(0, "rgba(50,50,200,0.8)");
                  lg.addColorStop(0.5, "rgba(50,180,80,0.8)");
                  lg.addColorStop(1, "rgba(50,220,120,0.8)");
                  ctx.fillStyle = lg;
                  ctx.fillRect(10, 122, 130, 8);
                  ctx.fillStyle = "rgba(255,255,255,0.8)";
                  ctx.font = "7px sans-serif";
                  ctx.textAlign = "left";
                  ctx.fillText("Flooded", 10, 118);
                  ctx.textAlign = "right";
                  ctx.fillText("Healthy Planted", 140, 118);
                  ctx.textAlign = "left";
                }}
              />
            </div>

            {/* Results Table */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[11px] font-semibold">Per-Farm SAR Results</p>
                <select
                  value={filterMuni}
                  onChange={e => setFilterMuni(e.target.value)}
                  className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background"
                >
                  {MUNICIPALITIES.map(m => <option key={m}>{m}</option>)}
                </select>
              </div>
              <div className="border border-border rounded-lg overflow-hidden">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="bg-[#166534] text-white">
                      <th className="px-2 py-1.5 text-left font-semibold">Farm</th>
                      <th className="px-2 py-1.5 text-left font-semibold">Municipality</th>
                      <th className="px-2 py-1.5 text-center font-semibold">Planted %</th>
                      <th className="px-2 py-1.5 text-center font-semibold">Flooded %</th>
                      <th className="px-2 py-1.5 text-center font-semibold">NDVI</th>
                      <th className="px-2 py-1.5 text-center font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredResults.map((r, i) => {
                      const s = STATUS_STYLE[r.status];
                      return (
                        <tr key={r.farmId} className={`border-t border-border ${i%2===0?"":"bg-muted/10"}`}>
                          <td className="px-2 py-1.5 font-mono text-[#166534]">{r.farmId}</td>
                          <td className="px-2 py-1.5">{r.municipality}</td>
                          <td className="px-2 py-1.5 text-center">
                            <div className="flex items-center gap-1 justify-center">
                              <div className="w-12 h-1.5 rounded-full bg-muted overflow-hidden">
                                <div className="h-full rounded-full bg-emerald-500" style={{ width:`${r.sarPlantedPct}%` }} />
                              </div>
                              <span className="text-emerald-700 font-bold">{r.sarPlantedPct}%</span>
                            </div>
                          </td>
                          <td className="px-2 py-1.5 text-center">
                            <span className={r.sarFloodedPct > 50 ? "text-red-600 font-bold" : "text-muted-foreground"}>
                              {r.sarFloodedPct}%
                            </span>
                          </td>
                          <td className="px-2 py-1.5 text-center font-mono">
                            <span className={r.ndviIndex < 0.3 ? "text-amber-600" : "text-[#166534]"}>{r.ndviIndex}</span>
                          </td>
                          <td className="px-2 py-1.5 text-center">
                            <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-medium ${s.cls}`}>{s.label}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Export */}
            <button
              onClick={() => {
                const headers = ["FARM_ID","FARMER_NAME","MUNICIPALITY","AREA_HA","SAR_PLANTED_PCT","SAR_FLOODED_PCT","NDVI_INDEX","STATUS"];
                const rows = filteredResults.map(r => [
                  r.farmId, `"${r.farmerName}"`, r.municipality,
                  r.areaHa.toFixed(2), r.sarPlantedPct, r.sarFloodedPct,
                  r.ndviIndex, r.status,
                ]);
                const csv = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
                const uri = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
                const a = document.createElement("a");
                a.setAttribute("href", uri);
                a.setAttribute("download", `SAR_Analysis_Results_${dateFrom}_${dateTo}.csv`);
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
              }}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 border-[#166534] text-[#166534] text-xs font-bold hover:bg-[#166534]/5 transition-all"
            >
              <Download size={13} /> Export SAR Results as CSV
            </button>
            <button
              onClick={() => setStep("form")}
              className="w-full text-[11px] text-muted-foreground hover:text-foreground transition-colors py-1"
            >
              ← Run Another Analysis
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
