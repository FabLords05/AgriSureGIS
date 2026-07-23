import { useState, useEffect, useRef } from "react";
import {
  Activity, Download, CheckCircle, Clock, AlertTriangle, FileDown,
  Wifi, RefreshCw, Eye, ChevronRight, BarChart2, TrendingUp, Zap,
  Satellite, X, MapPin, User, FileText
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid, Legend
} from "recharts";
import { mockBulletins, mockFarmers, TCBBulletin, FarmerRecord } from "./mockData";

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

const statusColors: Record<TCBBulletin["status"], { bg: string; text: string; label: string }> = {
  processed:   { bg:"bg-emerald-100 dark:bg-emerald-900/30", text:"text-emerald-700 dark:text-emerald-400", label:"Processed" },
  parsed:      { bg:"bg-blue-100 dark:bg-blue-900/30",       text:"text-blue-700 dark:text-blue-400",       label:"Parsed"    },
  downloaded:  { bg:"bg-amber-100 dark:bg-amber-900/30",     text:"text-amber-700 dark:text-amber-400",     label:"Downloaded"},
  downloading: { bg:"bg-gray-100 dark:bg-gray-800",          text:"text-gray-500",                          label:"Fetching…" },
};

const signalBadgeStyles: Record<number, string> = {
  1: "bg-emerald-100 text-emerald-700 border-emerald-200",
  2: "bg-amber-100 text-amber-700 border-amber-200",
  3: "bg-red-100 text-red-700 border-red-200",
  4: "bg-purple-100 text-purple-700 border-purple-200",
  5: "bg-gray-800 text-white border-gray-700",
};

// ─── TCB PDF Viewer Modal ────────────────────────────────────────────────────
function TCBViewerModal({ bulletin, onClose }: { bulletin: TCBBulletin; onClose: () => void }) {
  const signalColor = bulletin.signalNo === 3 ? "#ef4444" : bulletin.signalNo === 2 ? "#d97706" : "#166534";

  const handleDownloadTCB = () => {
    const content = [
      "PHILIPPINE ATMOSPHERIC, GEOPHYSICAL AND ASTRONOMICAL SERVICES ADMINISTRATION",
      "PAGASA — Tropical Cyclone Bulletin",
      "═══════════════════════════════════════════════════════════════════",
      "",
      `BULLETIN NO.: ${bulletin.bulletinNo}`,
      `TROPICAL CYCLONE: ${bulletin.cycloneName.toUpperCase()}`,
      `ISSUED BY: ${bulletin.issuedBy}`,
      `DATE/TIME: ${bulletin.issueDateTime}`,
      `WIND SIGNAL: SIGNAL NO. ${bulletin.signalNo} (${bulletin.windVelocityRange})`,
      `FILE SIZE: ${bulletin.fileSize}`,
      `VERSION: v${bulletin.version}`,
      "",
      "AREAS UNDER PUBLIC STORM WARNING SIGNAL:",
      ...bulletin.affectedAreas.map(a => `  • ${a}`),
      "",
      `SIGNAL NO. ${bulletin.signalNo} — Wind speed ${bulletin.windVelocityRange}`,
      "",
      "AFFECTED PROVINCES AND MUNICIPALITIES (CAMARINES SUR):",
      "  • Naga City (All barangays)",
      "  • Pili (All barangays)",
      "  • Libmanan (All barangays)",
      "  • Sipocot (All barangays)",
      "  • Goa (All barangays)",
      "  • Lagonoy (All barangays)",
      "",
      "AGRICULTURAL IMPACT ADVISORY:",
      "  • Rice farmers in affected municipalities are advised to harvest",
      "    mature crops immediately if feasible.",
      "  • PCIC insured farmers should document crop conditions for",
      "    indemnification claims.",
      "",
      "STATUS: " + bulletin.status.toUpperCase(),
      "",
      "═══════════════════════════════════════════════════════════════════",
      "This bulletin is intended for PCIC risk assessment purposes.",
      "Source: PAGASA Tropical Cyclone Bulletin System",
    ].join("\n");

    const uri = "data:text/plain;charset=utf-8," + encodeURIComponent(content);
    const a = document.createElement("a");
    a.setAttribute("href", uri);
    a.setAttribute("download", `PAGASA_${bulletin.cycloneName}_${bulletin.bulletinNo.replace(/ /g,"_")}.txt`);
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
            <FileText size={15} className="text-emerald-400" />
            <div>
              <p className="text-[12px] font-bold text-white">{bulletin.bulletinNo} — Tropical Cyclone {bulletin.cycloneName}</p>
              <p className="text-[10px] text-white/60">{bulletin.issuedBy} · {bulletin.issueDateTime}</p>
            </div>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>

        {/* Document body */}
        <div className="flex-1 overflow-auto p-5 font-mono text-[11px] bg-[#fafafa] dark:bg-[#0f1a0f]">
          <div className="space-y-3">
            {/* PAGASA letterhead */}
            <div className="text-center border-b border-border pb-3">
              <p className="font-bold text-[13px] uppercase tracking-wide">Philippine Atmospheric, Geophysical</p>
              <p className="font-bold text-[13px] uppercase tracking-wide">And Astronomical Services Administration</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">PAGASA — Tropical Cyclone Bulletin</p>
            </div>

            {/* Signal badge */}
            <div className="flex items-center justify-center">
              <div className="px-6 py-3 rounded-xl border-2 text-center" style={{ borderColor: signalColor, background: signalColor + "15" }}>
                <p className="text-[10px] uppercase tracking-widest" style={{ color: signalColor }}>Public Storm Warning Signal</p>
                <p className="text-3xl font-black" style={{ color: signalColor }}>No. {bulletin.signalNo}</p>
                <p className="text-[11px] font-semibold mt-0.5" style={{ color: signalColor }}>{bulletin.windVelocityRange}</p>
              </div>
            </div>

            {/* Bulletin details */}
            <div className="grid grid-cols-2 gap-2 text-[10px]">
              {[
                ["Bulletin No.", bulletin.bulletinNo],
                ["Cyclone Name", bulletin.cycloneName],
                ["Issued By", bulletin.issuedBy],
                ["Date / Time", bulletin.issueDateTime],
                ["Wind Velocity", bulletin.windVelocityRange],
                ["File Size", bulletin.fileSize],
                ["Version", "v" + bulletin.version],
                ["Status", bulletin.status.toUpperCase()],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-muted-foreground w-28 shrink-0">{k}:</span>
                  <span className="font-semibold">{v}</span>
                </div>
              ))}
            </div>

            {/* Affected areas */}
            <div className="border border-border rounded-lg p-3">
              <p className="font-bold text-[11px] mb-2 uppercase tracking-wide">Areas Under Storm Warning Signal No. {bulletin.signalNo}</p>
              <ul className="space-y-0.5">
                {bulletin.affectedAreas.map((a, i) => (
                  <li key={i} className="flex items-center gap-2 text-[10px]">
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: signalColor }} />
                    {a}
                  </li>
                ))}
              </ul>
            </div>

            {/* PCIC advisory */}
            <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 rounded-lg p-3">
              <p className="font-bold text-[10px] text-amber-700 mb-1">PCIC Agricultural Advisory</p>
              <p className="text-[10px] text-amber-700 leading-relaxed">
                Rice farmers in affected municipalities should document crop conditions. PCIC insured beneficiaries under RSBSA may be eligible for indemnification. All records have been cross-referenced with the RSBSA farmer registry for Camarines Sur.
              </p>
            </div>

            <p className="text-[9px] text-muted-foreground text-center pt-1">
              This bulletin is used for PCIC risk assessment and indemnification processing. Source: PAGASA TCB System.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
          <p className="text-[10px] text-muted-foreground">{bulletin.fileSize} · Version {bulletin.version}</p>
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

// ─── SAR Quick-View Modal ────────────────────────────────────────────────────
function SARQuickViewModal({ farmer, onClose }: { farmer: FarmerRecord; onClose: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width, H = canvas.height;

    // Deterministic seed from farmId
    let seed = farmer.rowId * 1234567;
    const rand = () => { seed = (seed * 16807 + 0) % 2147483647; return seed / 2147483647; };

    // SAR false-color background (dark = water/flood, bright = soil/veg)
    const imgData = ctx.createImageData(W, H);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        // Base terrain noise
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

    // Farm outline
    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 3]);
    const fw = W * 0.45, fh = H * 0.42;
    const fx = (W - fw) / 2, fy = (H - fh) / 2;
    ctx.strokeRect(fx, fy, fw, fh);
    ctx.setLineDash([]);

    // Flood extent overlay
    ctx.fillStyle = "rgba(30, 100, 220, 0.35)";
    ctx.fillRect(fx + fw * 0.1, fy + fh * 0.6, fw * 0.65, fh * 0.35);

    // Farm label
    ctx.fillStyle = "#fbbf24";
    ctx.font = "bold 10px monospace";
    ctx.fillText(farmer.farmId, fx + 4, fy - 4);

    // Legend
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
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border" style={{ background: "#0f1e0f" }}>
          <div className="flex items-center gap-2.5">
            <Satellite size={15} className="text-emerald-400" />
            <div>
              <p className="text-[12px] font-bold text-white">Sentinel-1 SAR Imagery — {farmer.farmId}</p>
              <p className="text-[10px] text-white/60">Google Earth Engine · C-Band SAR · VV+VH · 01 Nov 2024</p>
            </div>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* SAR Canvas */}
          <div className="flex-1 bg-black relative">
            <canvas ref={canvasRef} width={420} height={280} className="w-full h-full object-contain" />
            <div className="absolute top-2 right-2 flex flex-col gap-1">
              {["VV", "VH", "RGB"].map(b => (
                <button key={b} className="px-2 py-0.5 rounded bg-black/60 border border-white/20 text-white text-[9px] hover:bg-white/10 transition-colors">{b}</button>
              ))}
            </div>
          </div>

          {/* Info Panel */}
          <div className="w-52 shrink-0 border-l border-border flex flex-col overflow-auto bg-card">
            {/* Farm Info */}
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

            {/* SAR Metrics */}
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

            {/* Flood risk */}
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

        {/* Footer */}
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
  const [bulletins, setBulletins] = useState(mockBulletins);
  const [parserPulse, setParserPulse] = useState(true);
  const [lastCheck, setLastCheck] = useState("15:05 PHT");
  const [selectedBulletin, setSelectedBulletin] = useState<TCBBulletin | null>(null);
  const [showNewAlert, setShowNewAlert] = useState(false);
  const [sarFarmer, setSarFarmer] = useState<FarmerRecord | null>(null);
  const [viewingTCB, setViewingTCB] = useState<TCBBulletin | null>(null);

  const totalFarms = mockFarmers.length;
  const plantedFarms = mockFarmers.filter(f => f.planted).length;
  const totalArea = mockFarmers.reduce((s, f) => s + (f.planted ? f.areaHectare : 0), 0);
  const totalIndemnity = mockFarmers.reduce((s, f) => s + f.indemnityPayment, 0);

  useEffect(() => {
    const t = setTimeout(() => {
      setShowNewAlert(true);
      setTimeout(() => setShowNewAlert(false), 6000);
    }, 4000);
    return () => clearTimeout(t);
  }, []);

  const statCards = [
    { label:"Active Typhoon",       value:"Pepito",       sub:"Signal No. 3 peak", icon:<Zap size={18} />,        color:"#ef4444", bg:"bg-red-50 dark:bg-red-950/30",     border:"border-red-200 dark:border-red-900" },
    { label:"TCBs Downloaded",      value:bulletins.length, sub:"6 versions stored",  icon:<Download size={18} />,   color:"#1e3a5f", bg:"bg-blue-50 dark:bg-blue-950/30",   border:"border-blue-200 dark:border-blue-900" },
    { label:"Affected Farms",       value:`${plantedFarms}/20`,  sub:`${totalArea.toFixed(1)} ha planted`,icon:<Activity size={18} />, color:"#166534", bg:"bg-green-50 dark:bg-green-950/30", border:"border-green-200 dark:border-green-900" },
    { label:"Est. Total Indemnity", value:`₱${(totalIndemnity/1000).toFixed(0)}K`, sub:"Pending finalization", icon:<BarChart2 size={18} />, color:"#ca8a04", bg:"bg-amber-50 dark:bg-amber-950/30", border:"border-amber-200 dark:border-amber-900" },
  ];

  return (
    <div className="h-full overflow-auto bg-background p-4 space-y-4">
      {sarFarmer && <SARQuickViewModal farmer={sarFarmer} onClose={() => setSarFarmer(null)} />}
      {viewingTCB && <TCBViewerModal bulletin={viewingTCB} onClose={() => setViewingTCB(null)} />}

      {/* New Bulletin Alert */}
      {showNewAlert && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-xl border border-blue-200 bg-blue-50 dark:bg-blue-900/60 shadow-2xl animate-bounce">
          <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-sm font-semibold text-blue-700 dark:text-blue-300">New TCB Parsed — Typhoon Pepito TCB No. 6 is ready.</span>
          <button onClick={() => setShowNewAlert(false)} className="text-blue-400 hover:text-blue-600 ml-2">✕</button>
        </div>
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
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">Typhoon Pepito</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[10px] text-muted-foreground">Parser monitoring PAGASA</span>
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/50 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-semibold">Bulletin</th>
                  <th className="px-3 py-2 text-left font-semibold">Issued</th>
                  <th className="px-3 py-2 text-left font-semibold">Signal</th>
                  <th className="px-3 py-2 text-left font-semibold">Wind Speed</th>
                  <th className="px-3 py-2 text-left font-semibold">Affected Areas</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody>
                {bulletins.map(b => {
                  const st = statusColors[b.status];
                  return (
                    <tr
                      key={b.id}
                      className={`border-t border-border hover:bg-muted/30 cursor-pointer transition-colors ${selectedBulletin?.id === b.id ? "bg-[#166534]/10" : ""}`}
                      onClick={() => setSelectedBulletin(b)}
                    >
                      <td className="px-3 py-2.5 font-semibold">{b.bulletinNo}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{b.issueDateTime}</td>
                      <td className="px-3 py-2.5">
                        <span className={`px-1.5 py-0.5 rounded border text-[10px] font-bold ${signalBadgeStyles[b.signalNo]}`}>
                          No. {b.signalNo}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">{b.windVelocityRange}</td>
                      <td className="px-3 py-2.5 text-muted-foreground max-w-[160px] truncate" title={b.affectedAreas.join(", ")}>
                        {b.affectedAreas.slice(0,2).join(", ")}{b.affectedAreas.length > 2 ? `+${b.affectedAreas.length - 2}` : ""}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${st.bg} ${st.text}`}>
                          {b.status === "downloading" ? <span className="flex items-center gap-1"><RefreshCw size={8} className="animate-spin" />{st.label}</span> : st.label}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={e => { e.stopPropagation(); setViewingTCB(b); }}
                            className="p-1 hover:bg-muted rounded"
                            title="View TCB"
                          >
                            <Eye size={11} className="text-[#1e3a5f]" />
                          </button>
                          <button
                            onClick={e => {
                              e.stopPropagation();
                              const content = [
                                "PAGASA TROPICAL CYCLONE BULLETIN",
                                `Bulletin: ${b.bulletinNo}`,
                                `Cyclone: ${b.cycloneName}`,
                                `Issued: ${b.issueDateTime}`,
                                `Signal: No. ${b.signalNo} (${b.windVelocityRange})`,
                                `Areas: ${b.affectedAreas.join(", ")}`,
                                `Status: ${b.status}`,
                              ].join("\n");
                              const uri = "data:text/plain;charset=utf-8," + encodeURIComponent(content);
                              const a = document.createElement("a");
                              a.setAttribute("href", uri);
                              a.setAttribute("download", `${b.cycloneName}_${b.bulletinNo.replace(/ /g,"_")}.txt`);
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                            }}
                            className="p-1 hover:bg-muted rounded"
                            title="Download TCB"
                          >
                            <Download size={11} className="text-muted-foreground" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Selected bulletin detail + farmer SAR list */}
          {selectedBulletin && (
            <div className="border-t border-border bg-[#166534]/5">
              <div className="flex items-start justify-between px-4 py-2.5">
                <div>
                  <p className="text-[11px] font-bold text-[#166534]">{selectedBulletin.bulletinNo} — {selectedBulletin.cycloneName}</p>
                  <p className="text-[10px] text-muted-foreground">{selectedBulletin.issueDateTime} | {selectedBulletin.fileSize} | v{selectedBulletin.version}</p>
                  <p className="text-[10px] mt-0.5">Issued by: {selectedBulletin.issuedBy} | Wind: {selectedBulletin.windVelocityRange}</p>
                  <p className="text-[10px] text-muted-foreground">Areas: {selectedBulletin.affectedAreas.join(" • ")}</p>
                </div>
                <button onClick={() => setSelectedBulletin(null)} className="text-muted-foreground text-[10px] hover:text-foreground mt-0.5">✕</button>
              </div>
              {/* Farmer list with SAR quick-view */}
              <div className="border-t border-[#166534]/20 px-4 py-2">
                <div className="flex items-center gap-2 mb-1.5">
                  <Satellite size={11} className="text-[#166534]" />
                  <p className="text-[10px] font-semibold">Affected Farmers — Click to view SAR Imagery</p>
                  <span className="text-[9px] text-muted-foreground ml-auto">Signal {selectedBulletin.signalNo} matches</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {mockFarmers
                    .filter(f => f.signalNo === selectedBulletin.signalNo && f.planted)
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
                { label:"PAGASA Parser",    ok:true,  detail:"Monitoring every 3h" },
                { label:"GEE Connection",   ok:true,  detail:"1000 EEC allocated"  },
                { label:"Email Alerts",     ok:true,  detail:"SMTP connected"      },
                { label:"Database Backup",  ok:false, detail:"Last: 30 Oct 2024"   },
                { label:"Session Monitor",  ok:true,  detail:"5-min timeout active"},
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
              <span className="text-[10px] text-muted-foreground">Last check: {lastCheck}</span>
            </div>
          </div>

          {/* Growth Stage Pie */}
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

      {/* Bottom Charts Row */}
      <div className="grid grid-cols-2 gap-4">
        {/* Signal Distribution Bar */}
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

        {/* Bulletin Timeline Line */}
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
