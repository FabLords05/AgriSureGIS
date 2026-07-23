import { useState, useEffect, useRef, useCallback } from "react";
import {
  Activity, Download, CheckCircle, Clock, AlertTriangle, FileDown,
  Wifi, RefreshCw, Eye, BarChart2, TrendingUp, Zap,
  Satellite, X, MapPin, User
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid, Legend
} from "recharts";
import { mockFarmers, FarmerRecord } from "./mockData";
import { Bulletin, TcbSignal, getBulletins, parseBulletins, getBulletinSignals } from "@/lib/api";

const signalChartData = [
  { signal:"Signal 1", farms:6,  area:12.0 },
  { signal:"Signal 2", farms:11, area:26.0 },
  { signal:"Signal 3", farms:5,  area:14.5 },
];

const growthPieData = [
  { name:"Seedling",     value:5, color:"#86efac" },
  { name:"Vegetative",   value:6, color:"#22c55e" },
  { name:"Reproductive", value:5, color:"#eab308" },
  { name:"Ripening",     value:4, color:"#f59e0b" },
];

const timelineData = [
  { time:"00:00", bulletins:1, farms:0 },
  { time:"03:00", bulletins:2, farms:5 },
  { time:"06:00", bulletins:3, farms:11 },
  { time:"09:00", bulletins:4, farms:16 },
  { time:"12:00", bulletins:5, farms:19 },
  { time:"15:00", bulletins:6, farms:19 },
];

function uniqueAreas(signals: TcbSignal[]): string[] {
  return Array.from(new Set(signals.map(s => s.area_name)));
}

function maxSignalLevel(signals: TcbSignal[]): number {
  return signals.length ? Math.max(...signals.map(s => s.signal_level)) : 0;
}

// ─── TCB Detail Viewer Modal ─────────────────────────────────────────────────
function TCBViewerModal({ bulletin, signals, isLoadingSignals, onClose }: { bulletin: Bulletin; signals: TcbSignal[]; isLoadingSignals: boolean; onClose: () => void }) {
  const highestSignal = maxSignalLevel(signals);
  const signalColor = highestSignal === 3 ? "#ef4444" : highestSignal === 2 ? "#d97706" : "#166534";
  const areas = uniqueAreas(signals);

  const handleDownloadTCB = () => {
    const content = [
      "PHILIPPINE ATMOSPHERIC, GEOPHYSICAL AND ASTRONOMICAL SERVICES ADMINISTRATION",
      "PAGASA — Tropical Cyclone Bulletin",
      "═══════════════════════════════════════════════════════════════════",
      "",
      `TITLE: ${bulletin.title}`,
      `TROPICAL CYCLONE: ${bulletin.typhoon_name.toUpperCase()}`,
      `BULLETIN NO.: ${bulletin.bulletin_count}`,
      `CATEGORY: ${bulletin.category ?? "Unknown"}`,
      `ISSUED: ${bulletin.issued_at ?? "Unknown"}`,
      `MAX SUSTAINED WINDS: ${bulletin.max_sustained_winds ?? "—"} km/h`,
      `GUSTINESS: ${bulletin.gustiness ?? "—"} km/h`,
      "",
      "AREAS UNDER SIGNAL WARNING:",
      ...(areas.length ? areas.map(a => `  • ${a}`) : ["  (no signal data recorded for this bulletin)"]),
      "",
      "═══════════════════════════════════════════════════════════════════",
      "This bulletin is intended for PCIC risk assessment purposes.",
      "Source: PAGASA Tropical Cyclone Bulletin System",
    ].join("\n");

    const uri = "data:text/plain;charset=utf-8," + encodeURIComponent(content);
    const a = document.createElement("a");
    a.setAttribute("href", uri);
    a.setAttribute("download", `PAGASA_${bulletin.typhoon_name}_TCB${bulletin.bulletin_count}.txt`);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[680px] max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0" style={{ background: "#0f1e0f" }}>
          <div className="flex items-center gap-3">
            <FileDown size={15} className="text-emerald-400" />
            <div>
              <p className="text-[12px] font-bold text-white">TCB No. {bulletin.bulletin_count} — Tropical Cyclone {bulletin.typhoon_name}</p>
              <p className="text-[10px] text-white/60">{bulletin.issued_at ?? "Unknown date"}</p>
            </div>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>

        {/* Document body */}
        <div className="flex-1 overflow-auto p-5 font-mono text-[11px] bg-[#fafafa] dark:bg-[#0f1a0f]">
          <div className="space-y-3">
            <div className="text-center border-b border-border pb-3">
              <p className="font-bold text-[13px] uppercase tracking-wide">Philippine Atmospheric, Geophysical</p>
              <p className="font-bold text-[13px] uppercase tracking-wide">And Astronomical Services Administration</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">PAGASA — Tropical Cyclone Bulletin</p>
            </div>

            <div className="flex items-center justify-center">
              <div className="px-6 py-3 rounded-xl border-2 text-center" style={{ borderColor: signalColor, background: signalColor + "15" }}>
                <p className="text-[10px] uppercase tracking-widest" style={{ color: signalColor }}>{bulletin.category ?? "Tropical Cyclone"}</p>
                <p className="text-3xl font-black" style={{ color: signalColor }}>
                  {isLoadingSignals ? "…" : highestSignal > 0 ? `Signal No. ${highestSignal}` : "No Signal Data"}
                </p>
                <p className="text-[11px] font-semibold mt-0.5" style={{ color: signalColor }}>
                  {bulletin.max_sustained_winds ?? "—"} km/h sustained · gusts {bulletin.gustiness ?? "—"} km/h
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[10px]">
              {[
                ["Title", bulletin.title],
                ["Cyclone Name", bulletin.typhoon_name],
                ["Bulletin No.", String(bulletin.bulletin_count)],
                ["Category", bulletin.category ?? "Unknown"],
                ["Issued", bulletin.issued_at ?? "Unknown"],
                ["Max Winds", `${bulletin.max_sustained_winds ?? "—"} km/h`],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-muted-foreground w-28 shrink-0">{k}:</span>
                  <span className="font-semibold">{v}</span>
                </div>
              ))}
            </div>

            <div className="border border-border rounded-lg p-3">
              <p className="font-bold text-[11px] mb-2 uppercase tracking-wide">Areas Under Signal Warning</p>
              {isLoadingSignals ? (
                <p className="text-[10px] text-muted-foreground">Loading affected areas…</p>
              ) : areas.length ? (
                <ul className="space-y-0.5">
                  {areas.map((a, i) => (
                    <li key={i} className="flex items-center gap-2 text-[10px]">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: signalColor }} />
                      {a}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[10px] text-muted-foreground">No signal/area data recorded for this bulletin.</p>
              )}
            </div>

            <p className="text-[9px] text-muted-foreground text-center pt-1">
              This bulletin is used for PCIC risk assessment and indemnification processing. Source: PAGASA TCB System.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
          <p className="text-[10px] text-muted-foreground">TCB ID {bulletin.tcb_id}</p>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Close</button>
            <button
              onClick={handleDownloadTCB}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#1e3a5f] text-white text-xs font-semibold hover:bg-[#172f4d] transition-colors"
            >
              <Download size={12} /> Download TCB
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── SAR Quick-View Modal (mock — no backend GEE integration exists yet) ────
function SARQuickViewModal({ farmer, onClose }: { farmer: FarmerRecord; onClose: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width, H = canvas.height;

    let seed = farmer.rowId * 1234567;
    const rand = () => { seed = (seed * 16807 + 0) % 2147483647; return seed / 2147483647; };

    const imgData = ctx.createImageData(W, H);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        const n = rand();
        const isFloodArea = y > H * 0.55 && x > W * 0.3 && x < W * 0.75 && n > 0.35;
        const isFarmArea  = x > W * 0.25 && x < W * 0.75 && y > H * 0.25 && y < H * 0.75;
        const brightness  = n * 180;
        if (isFloodArea) {
          imgData.data[i]   = Math.floor(10 + rand() * 20);
          imgData.data[i+1] = Math.floor(20 + rand() * 40);
          imgData.data[i+2] = Math.floor(60 + rand() * 60);
        } else if (isFarmArea) {
          const v = Math.floor(50 + rand() * 100);
          imgData.data[i]   = Math.floor(v * 0.3);
          imgData.data[i+1] = Math.floor(v * 0.8);
          imgData.data[i+2] = Math.floor(v * 0.4);
        } else {
          imgData.data[i]   = Math.floor(brightness * 0.5);
          imgData.data[i+1] = Math.floor(brightness * 0.5);
          imgData.data[i+2] = Math.floor(brightness * 0.4);
        }
        imgData.data[i+3] = 255;
      }
    }
    ctx.putImageData(imgData, 0, 0);

    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 3]);
    const fw = W * 0.45, fh = H * 0.42;
    const fx = (W - fw) / 2, fy = (H - fh) / 2;
    ctx.strokeRect(fx, fy, fw, fh);
    ctx.setLineDash([]);

    ctx.fillStyle = "rgba(30, 100, 220, 0.35)";
    ctx.fillRect(fx + fw * 0.1, fy + fh * 0.6, fw * 0.65, fh * 0.35);

    ctx.fillStyle = "#fbbf24";
    ctx.font = "bold 10px monospace";
    ctx.fillText(farmer.farmId, fx + 4, fy - 4);

    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.fillRect(4, H - 32, 130, 28);
    ctx.fillStyle = "#86efac"; ctx.fillRect(8, H - 28, 8, 8);
    ctx.fillStyle = "#fff"; ctx.font = "9px sans-serif";
    ctx.fillText("Planted Area", 20, H - 20);
    ctx.fillStyle = "rgba(30,100,220,0.7)"; ctx.fillRect(8, H - 18, 8, 8);
    ctx.fillStyle = "#fff"; ctx.fillText("Flood Extent", 20, H - 10);

  }, [farmer]);

  const floodPct = 25 + (farmer.rowId * 7) % 45;
  const plantedPct = 60 + (farmer.rowId * 13) % 35;
  const coherence = (0.42 + (farmer.rowId * 0.037) % 0.4).toFixed(2);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[700px] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border" style={{ background: "#0f1e0f" }}>
          <div className="flex items-center gap-2.5">
            <Satellite size={15} className="text-emerald-400" />
            <div>
              <p className="text-[12px] font-bold text-white">Sentinel-1 SAR Imagery — {farmer.farmId}</p>
              <p className="text-[10px] text-white/60">Google Earth Engine · C-Band SAR · VV+VH · simulated preview</p>
            </div>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div className="flex-1 bg-black relative">
            <canvas ref={canvasRef} width={420} height={280} className="w-full h-full object-contain" />
            <div className="absolute top-2 right-2 flex flex-col gap-1">
              {["VV", "VH", "RGB"].map(b => (
                <button key={b} className="px-2 py-0.5 rounded bg-black/60 border border-white/20 text-white text-[9px] hover:bg-white/10 transition-colors">{b}</button>
              ))}
            </div>
          </div>

          <div className="w-52 shrink-0 border-l border-border flex flex-col overflow-auto bg-card">
            <div className="px-3 py-2.5 border-b border-border">
              <div className="flex items-center gap-1.5 mb-2">
                <User size={11} className="text-[#166534]" />
                <p className="text-[11px] font-bold">{farmer.insuredName}</p>
              </div>
              <div className="space-y-1 text-[10px]">
                <div className="flex justify-between"><span className="text-muted-foreground">Farm ID</span><span className="font-mono text-[#166534]">{farmer.farmId}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Municipality</span><span>{farmer.municipality}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Area</span><span>{farmer.areaHectare.toFixed(2)} ha</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Growth Stage</span><span className="font-medium">{farmer.growthStage}</span></div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Signal</span>
                  <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${farmer.signalNo === 2 ? "bg-amber-100 text-amber-700 border-amber-200" : farmer.signalNo === 3 ? "bg-red-100 text-red-700 border-red-200" : "bg-emerald-100 text-emerald-700 border-emerald-200"}`}>
                    S{farmer.signalNo}
                  </span>
                </div>
              </div>
            </div>

            <div className="px-3 py-2.5 border-b border-border">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">SAR Metrics</p>
              <div className="space-y-2">
                {[
                  { label: "Flood Extent", value: `${floodPct}%`, color: "text-blue-600" },
                  { label: "Planted Area", value: `${plantedPct}%`, color: "text-emerald-600" },
                  { label: "Coherence", value: coherence, color: "text-purple-600" },
                  { label: "Pass Dir.", value: "Descending", color: "" },
                  { label: "Resolution", value: "10m × 10m", color: "" },
                ].map((m, i) => (
                  <div key={i} className="flex justify-between items-center">
                    <span className="text-[10px] text-muted-foreground">{m.label}</span>
                    <span className={`text-[10px] font-bold ${m.color}`}>{m.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="px-3 py-2.5">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">Flood Risk Assessment</p>
              <div className="w-full h-2 rounded-full bg-muted overflow-hidden mb-1">
                <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${floodPct}%` }} />
              </div>
              <p className="text-[9px] text-muted-foreground">{floodPct}% of farm polygon shows backscatter consistent with inundation.</p>
              <div className={`mt-2 px-2 py-1.5 rounded-lg text-[10px] font-medium ${floodPct > 50 ? "bg-red-100 text-red-700" : floodPct > 25 ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>
                {floodPct > 50 ? "High Flood Risk — Recommend field verification" : floodPct > 25 ? "Moderate — Confirm with ground survey" : "Low — SAR shows minimal inundation"}
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between px-4 py-2 border-t border-border bg-muted/20 shrink-0">
          <p className="text-[9px] text-muted-foreground">Simulated GEE Sentinel-1 result · For assessment reference only · Verify with field data</p>
          <button onClick={onClose} className="px-3 py-1 rounded-lg bg-[#166534] text-white text-[10px] font-semibold hover:bg-[#14532d] transition-colors">Close</button>
        </div>
      </div>
    </div>
  );
}

interface MonitoringModuleProps {
  darkMode: boolean;
}

export function MonitoringModule({ darkMode }: MonitoringModuleProps) {
  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [isLoadingBulletins, setIsLoadingBulletins] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastCheck, setLastCheck] = useState<string | null>(null);

  const [selectedBulletin, setSelectedBulletin] = useState<Bulletin | null>(null);
  const [selectedSignals, setSelectedSignals] = useState<TcbSignal[]>([]);
  const [isLoadingSelectedSignals, setIsLoadingSelectedSignals] = useState(false);

  const [viewingTCB, setViewingTCB] = useState<Bulletin | null>(null);
  const [viewingSignals, setViewingSignals] = useState<TcbSignal[]>([]);
  const [isLoadingViewingSignals, setIsLoadingViewingSignals] = useState(false);

  const [sarFarmer, setSarFarmer] = useState<FarmerRecord | null>(null);

  const totalFarms = mockFarmers.length;
  const plantedFarms = mockFarmers.filter(f => f.planted).length;
  const totalArea = mockFarmers.reduce((s, f) => s + (f.planted ? f.areaHectare : 0), 0);
  const totalIndemnity = mockFarmers.reduce((s, f) => s + f.indemnityPayment, 0);

  const loadBulletins = useCallback(async () => {
    setIsLoadingBulletins(true);
    setLoadError(null);
    try {
      const data = await getBulletins();
      setBulletins(data);
      setLastCheck(new Date().toLocaleTimeString());
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Failed to load bulletins.");
    } finally {
      setIsLoadingBulletins(false);
    }
  }, []);

  useEffect(() => {
    loadBulletins();
  }, [loadBulletins]);

  const handleParseLatest = async () => {
    setIsParsing(true);
    setLoadError(null);
    try {
      await parseBulletins();
      await loadBulletins();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Failed to parse latest bulletin.");
    } finally {
      setIsParsing(false);
    }
  };

  const handleSelectBulletin = async (b: Bulletin) => {
    setSelectedBulletin(prev => (prev?.tcb_id === b.tcb_id ? null : b));
    if (selectedBulletin?.tcb_id === b.tcb_id) return;
    setSelectedSignals([]);
    setIsLoadingSelectedSignals(true);
    try {
      setSelectedSignals(await getBulletinSignals(b.tcb_id));
    } catch {
      setSelectedSignals([]);
    } finally {
      setIsLoadingSelectedSignals(false);
    }
  };

  const handleViewTCB = async (b: Bulletin) => {
    setViewingTCB(b);
    setViewingSignals([]);
    setIsLoadingViewingSignals(true);
    try {
      setViewingSignals(await getBulletinSignals(b.tcb_id));
    } catch {
      setViewingSignals([]);
    } finally {
      setIsLoadingViewingSignals(false);
    }
  };

  const handleDownloadBulletinSummary = (b: Bulletin) => {
    const content = [
      "PAGASA TROPICAL CYCLONE BULLETIN",
      `Title: ${b.title}`,
      `Cyclone: ${b.typhoon_name}`,
      `Bulletin No.: ${b.bulletin_count}`,
      `Category: ${b.category ?? "Unknown"}`,
      `Issued: ${b.issued_at ?? "Unknown"}`,
      `Max Sustained Winds: ${b.max_sustained_winds ?? "—"} km/h`,
      `Gustiness: ${b.gustiness ?? "—"} km/h`,
    ].join("\n");
    const uri = "data:text/plain;charset=utf-8," + encodeURIComponent(content);
    const a = document.createElement("a");
    a.setAttribute("href", uri);
    a.setAttribute("download", `${b.typhoon_name}_TCB${b.bulletin_count}.txt`);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const latestBulletin = bulletins[0];
  const selectedMaxSignal = maxSignalLevel(selectedSignals);

  const statCards = [
    { label:"Active Typhoon",       value: latestBulletin?.typhoon_name ?? "—", sub: latestBulletin?.category ?? "No bulletins yet", icon:<Zap size={18} />,        color:"#ef4444", bg:"bg-red-50 dark:bg-red-950/30",     border:"border-red-200 dark:border-red-900" },
    { label:"TCBs Downloaded",      value: bulletins.length, sub:"from PAGASA parser",  icon:<Download size={18} />,   color:"#1e3a5f", bg:"bg-blue-50 dark:bg-blue-950/30",   border:"border-blue-200 dark:border-blue-900" },
    { label:"Affected Farms",       value:`${plantedFarms}/${totalFarms}`,  sub:`${totalArea.toFixed(1)} ha planted`,icon:<Activity size={18} />, color:"#166534", bg:"bg-green-50 dark:bg-green-950/30", border:"border-green-200 dark:border-green-900" },
    { label:"Est. Total Indemnity", value:`₱${(totalIndemnity/1000).toFixed(0)}K`, sub:"Pending finalization", icon:<BarChart2 size={18} />, color:"#ca8a04", bg:"bg-amber-50 dark:bg-amber-950/30", border:"border-amber-200 dark:border-amber-900" },
  ];

  return (
    <div className="h-full overflow-auto bg-background p-4 space-y-4">
      {sarFarmer && <SARQuickViewModal farmer={sarFarmer} onClose={() => setSarFarmer(null)} />}
      {viewingTCB && (
        <TCBViewerModal
          bulletin={viewingTCB}
          signals={viewingSignals}
          isLoadingSignals={isLoadingViewingSignals}
          onClose={() => setViewingTCB(null)}
        />
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-4 gap-3">
        {statCards.map((c, i) => (
          <div key={i} className={`bg-card border rounded-xl p-4 ${c.border}`}>
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] text-muted-foreground uppercase tracking-wide">{c.label}</p>
                <p className="text-2xl font-bold mt-0.5" style={{ color: c.color }}>{c.value}</p>
                <p className="text-[10px] text-muted-foreground mt-0.5">{c.sub}</p>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: c.color + "20", color: c.color }}>
                {c.icon}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* TCB Bulletin List */}
        <div className="col-span-2 bg-card border border-border rounded-xl flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <div className="flex items-center gap-2">
              <FileDown size={15} className="text-[#166534]" />
              <span className="text-sm font-semibold">PAGASA TCB Bulletins</span>
            </div>
            <button
              onClick={handleParseLatest}
              disabled={isParsing}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#166534] text-white text-[11px] font-medium hover:bg-[#14532d] disabled:opacity-50 transition-colors"
            >
              <RefreshCw size={11} className={isParsing ? "animate-spin" : ""} />
              {isParsing ? "Parsing…" : "Parse Latest Bulletin"}
            </button>
          </div>

          {loadError && (
            <div className="px-4 py-2 text-[11px] text-white bg-red-600">{loadError}</div>
          )}

          <div className="flex-1 overflow-auto">
            {isLoadingBulletins && bulletins.length === 0 ? (
              <p className="px-4 py-3 text-[11px] text-muted-foreground">Loading bulletins…</p>
            ) : bulletins.length === 0 ? (
              <p className="px-4 py-3 text-[11px] text-muted-foreground">No bulletins parsed yet.</p>
            ) : (
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-muted/50 text-muted-foreground">
                    <th className="px-3 py-2 text-left font-semibold">Bulletin</th>
                    <th className="px-3 py-2 text-left font-semibold">Typhoon</th>
                    <th className="px-3 py-2 text-left font-semibold">Issued</th>
                    <th className="px-3 py-2 text-left font-semibold">Category</th>
                    <th className="px-3 py-2 text-left font-semibold">Max Winds</th>
                    <th className="px-3 py-2 text-left font-semibold">Gust</th>
                    <th className="px-3 py-2 text-left font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {bulletins.map(b => (
                    <tr
                      key={b.tcb_id}
                      className={`border-t border-border hover:bg-muted/30 cursor-pointer transition-colors ${selectedBulletin?.tcb_id === b.tcb_id ? "bg-[#166534]/10" : ""}`}
                      onClick={() => handleSelectBulletin(b)}
                    >
                      <td className="px-3 py-2.5 font-semibold">TCB No. {b.bulletin_count}</td>
                      <td className="px-3 py-2.5">{b.typhoon_name}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{b.issued_at ?? "—"}</td>
                      <td className="px-3 py-2.5">{b.category ?? "—"}</td>
                      <td className="px-3 py-2.5">{b.max_sustained_winds ?? "—"} km/h</td>
                      <td className="px-3 py-2.5">{b.gustiness ?? "—"} km/h</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={e => { e.stopPropagation(); handleViewTCB(b); }}
                            className="p-1 hover:bg-muted rounded"
                            title="View TCB"
                          >
                            <Eye size={11} className="text-[#1e3a5f]" />
                          </button>
                          <button
                            onClick={e => { e.stopPropagation(); handleDownloadBulletinSummary(b); }}
                            className="p-1 hover:bg-muted rounded"
                            title="Download TCB Summary"
                          >
                            <Download size={11} className="text-muted-foreground" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Selected bulletin detail + farmer SAR list */}
          {selectedBulletin && (
            <div className="border-t border-border bg-[#166534]/5">
              <div className="flex items-start justify-between px-4 py-2.5">
                <div>
                  <p className="text-[11px] font-bold text-[#166534]">TCB No. {selectedBulletin.bulletin_count} — {selectedBulletin.typhoon_name}</p>
                  <p className="text-[10px] text-muted-foreground">{selectedBulletin.issued_at ?? "Unknown"} · {selectedBulletin.category ?? "Unknown category"}</p>
                  <p className="text-[10px] mt-0.5">Max winds: {selectedBulletin.max_sustained_winds ?? "—"} km/h · Gust: {selectedBulletin.gustiness ?? "—"} km/h</p>
                  <p className="text-[10px] text-muted-foreground">
                    Areas: {isLoadingSelectedSignals ? "Loading…" : (uniqueAreas(selectedSignals).join(" • ") || "No signal data recorded")}
                  </p>
                </div>
                <button onClick={() => setSelectedBulletin(null)} className="text-muted-foreground text-[10px] hover:text-foreground mt-0.5">✕</button>
              </div>
              {/* Farmer list with SAR quick-view, cross-referenced by the bulletin's highest recorded signal level */}
              {selectedMaxSignal > 0 && (
                <div className="border-t border-[#166534]/20 px-4 py-2">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Satellite size={11} className="text-[#166534]" />
                    <p className="text-[10px] font-semibold">Farmers Under Signal No. {selectedMaxSignal} — Click to view SAR Imagery</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {mockFarmers
                      .filter(f => f.signalNo === selectedMaxSignal && f.planted)
                      .slice(0, 10)
                      .map(f => (
                        <button
                          key={f.farmId}
                          onClick={() => setSarFarmer(f)}
                          className="flex items-center gap-1 px-2 py-1 rounded-lg bg-card border border-border hover:bg-[#166534] hover:text-white hover:border-[#166534] transition-all group text-[10px]"
                          title={`${f.insuredName} — ${f.municipality}`}
                        >
                          <MapPin size={9} className="text-[#166534] group-hover:text-white" />
                          <span className="font-mono">{f.farmId}</span>
                          <span className="text-muted-foreground group-hover:text-white/80 text-[9px]">{f.insuredName.split(" ").pop()}</span>
                          <Satellite size={8} className="text-muted-foreground group-hover:text-white/80 ml-0.5" />
                        </button>
                      ))
                    }
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Panel */}
        <div className="flex flex-col gap-4">
          {/* System Status */}
          <div className="bg-card border border-border rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Wifi size={14} className="text-[#166534]" />
              <span className="text-xs font-semibold">System Status</span>
            </div>
            <div className="space-y-2">
              {[
                { label:"Backend API",      ok: !loadError, detail: loadError ? "Unreachable" : "Connected" },
                { label:"GEE Connection",   ok:true,  detail:"1000 EEC allocated (mock)"  },
                { label:"Email Alerts",     ok:true,  detail:"SMTP connected (mock)"      },
                { label:"Database Backup",  ok:false, detail:"Last: 30 Oct 2024 (mock)"   },
                { label:"Session Monitor",  ok:true,  detail:"5-min timeout active (mock)"},
              ].map((s, i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {s.ok
                      ? <CheckCircle size={11} className="text-emerald-500 shrink-0" />
                      : <AlertTriangle size={11} className="text-amber-500 shrink-0" />
                    }
                    <span className="text-[11px]">{s.label}</span>
                  </div>
                  <span className="text-[10px] text-muted-foreground">{s.detail}</span>
                </div>
              ))}
            </div>
            <div className="mt-3 pt-2 border-t border-border flex items-center gap-1.5">
              <Clock size={10} className="text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground">Last check: {lastCheck ?? "—"}</span>
            </div>
          </div>

          {/* Growth Stage Pie (mock — no assessment endpoint match yet) */}
          <div className="bg-card border border-border rounded-xl p-4 flex-1">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp size={14} className="text-[#ca8a04]" />
              <span className="text-xs font-semibold">Growth Stage Distribution</span>
            </div>
            <ResponsiveContainer width="100%" height={130}>
              <PieChart>
                <Pie data={growthPieData} dataKey="value" cx="50%" cy="50%" innerRadius={30} outerRadius={55} paddingAngle={3}>
                  {growthPieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <RTooltip
                  contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
                  formatter={(v: number) => [`${v} farms`, ""]}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-x-2 gap-y-1 mt-1">
              {growthPieData.map(d => (
                <span key={d.name} className="flex items-center gap-1 text-[10px]">
                  <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: d.color }} />
                  {d.name} ({d.value})
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Charts Row (mock — no assessment endpoint match yet) */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 size={14} className="text-[#1e3a5f]" />
            <span className="text-xs font-semibold">Farms by Signal Number</span>
          </div>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={signalChartData} barSize={28}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#1c2e1c" : "#e5e7eb"} />
              <XAxis dataKey="signal" tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
              <RTooltip
                contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
              />
              <Bar dataKey="farms"  name="Farms"       fill="#166534" radius={[4,4,0,0]} />
              <Bar dataKey="area"   name="Area (ha)"   fill="#1e3a5f" radius={[4,4,0,0]} />
              <Legend iconSize={10} iconType="square" wrapperStyle={{ fontSize: 10 }} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-card border border-border rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity size={14} className="text-[#ef4444]" />
            <span className="text-xs font-semibold">TCB Download Timeline (01 Nov 2024)</span>
          </div>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={timelineData}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#1c2e1c" : "#e5e7eb"} />
              <XAxis dataKey="time" tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
              <RTooltip
                contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
              />
              <Line type="monotone" dataKey="bulletins" name="Bulletins"    stroke="#166534" strokeWidth={2} dot={{ r:3 }} />
              <Line type="monotone" dataKey="farms"     name="Farms Logged" stroke="#ca8a04" strokeWidth={2} dot={{ r:3 }} strokeDasharray="5 3" />
              <Legend iconSize={10} wrapperStyle={{ fontSize: 10 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

    </div>
  );
}
