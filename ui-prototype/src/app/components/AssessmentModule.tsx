import { useState, useMemo, useEffect } from "react";
import {
  FileText, Download, Eye, ChevronDown, ChevronUp, ArrowUpDown,
  CheckCircle2, Loader, BarChart2, Calculator, Pencil, X, Check,
  FolderOpen, Folder, AlertCircle, Wind, RefreshCw
} from "lucide-react";
import { mockFarmers, mockBulletins, FarmerRecord, TCBBulletin, SIGNAL_WIND_RANGES, DAMAGE_FACTORS } from "./mockData";
import { BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, CartesianGrid } from "recharts";

type SortField = keyof FarmerRecord;
type SortDir   = "asc" | "desc";

// ─── CSV Preview Modal (Step 1) ──────────────────────────────────────────────
interface CSVPreviewProps {
  farmers: FarmerRecord[];
  tcb: TCBBulletin;
  getEffectiveSI: (f: FarmerRecord) => number;
  getEffectivePayment: (f: FarmerRecord) => number;
  onClose: () => void;
  onConfirm: () => void;
}

function CSVPreviewModal({ farmers, tcb, getEffectiveSI, getEffectivePayment, onClose, onConfirm }: CSVPreviewProps) {
  const HEADERS = [
    "ROW_ID","FARMER_ID","INSURED_NAME","MUNICIPALITY","BARANGAY","FARM_ID",
    "AREA_HA","PLANTED","PLANTING_DATE","GROWTH_STAGE","CROP_TYPE",
    "SUM_INSURED_PHP","SIGNAL_NO","PERIOD_EXPOSURE_HRS","WIND_VEL_RANGE",
    "INDEMNITY_FACTOR_PCT","INDEMNITY_PAYMENT_PHP",
  ];
  const totalSI = farmers.reduce((s, f) => s + getEffectiveSI(f), 0);
  const totalPay = farmers.reduce((s, f) => s + Math.round(getEffectivePayment(f)), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[92vw] max-w-6xl max-h-[88vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#166534]/10 flex items-center justify-center">
              <Eye size={15} className="text-[#166534]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-bold">Step 1 — Review CSV Before Generating</p>
                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                  Signal 2 Only
                </span>
              </div>
              <p className="text-[10px] text-muted-foreground">
                PCIC Indemnification Report · {tcb.cycloneName} · {tcb.bulletinNo} · Camarines Sur
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        {/* Alert bar */}
        <div className="flex items-center gap-2 px-5 py-2 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-100 shrink-0">
          <AlertCircle size={11} className="text-blue-600 shrink-0" />
          <p className="text-[10px] text-blue-700 dark:text-blue-300">
            Please review all {farmers.length} records below before confirming download. This report covers only <strong>planted Signal No. 2 farms</strong>.
          </p>
        </div>

        {/* Table */}
        <div className="overflow-auto flex-1 px-1">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#166534] text-white">
                {HEADERS.map(h => (
                  <th key={h} className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {farmers.map((f, i) => (
                <tr key={f.farmId} className={`border-t border-border hover:bg-muted/30 ${i % 2 === 0 ? "bg-card" : "bg-muted/10"}`}>
                  <td className="px-2 py-1.5 text-muted-foreground">{f.rowId}</td>
                  <td className="px-2 py-1.5 font-mono">{f.farmerId}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">{f.insuredName}</td>
                  <td className="px-2 py-1.5">{f.municipality}</td>
                  <td className="px-2 py-1.5">{f.barangay}</td>
                  <td className="px-2 py-1.5 font-mono text-[#166534]">{f.farmId}</td>
                  <td className="px-2 py-1.5 text-right">{f.areaHectare.toFixed(2)}</td>
                  <td className="px-2 py-1.5">{f.planted ? "YES" : "NO"}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">{f.plantingDate}</td>
                  <td className="px-2 py-1.5">{f.growthStage}</td>
                  <td className="px-2 py-1.5">{f.cropType}</td>
                  <td className="px-2 py-1.5 text-right font-medium">₱{getEffectiveSI(f).toLocaleString()}</td>
                  <td className="px-2 py-1.5 font-bold text-center text-amber-600">S{f.signalNo}</td>
                  <td className="px-2 py-1.5 text-center">{f.periodOfExposure}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">{f.windVelocityMin > 0 ? `${f.windVelocityMin}–${f.windVelocityMax}` : "—"}</td>
                  <td className="px-2 py-1.5 text-right font-bold text-amber-600">{f.indemnityFactor}%</td>
                  <td className="px-2 py-1.5 text-right font-bold text-[#166534]">₱{Math.round(getEffectivePayment(f)).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border bg-muted/20 shrink-0">
          <div className="flex items-center gap-6 text-[11px]">
            <span className="text-muted-foreground"><strong className="text-foreground">{farmers.length}</strong> records</span>
            <span className="text-muted-foreground">Total SI: <strong className="text-[#ca8a04]">₱{totalSI.toLocaleString()}</strong></span>
            <span className="text-muted-foreground">Total Indemnity: <strong className="text-[#166534]">₱{totalPay.toLocaleString()}</strong></span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
            >
              <Download size={12} /> Step 2 — Confirm & Download CSV
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Download Confirm Modal (Step 2) ────────────────────────────────────────
interface DownloadConfirmProps {
  farmers: FarmerRecord[];
  tcb: TCBBulletin;
  getEffectiveSI: (f: FarmerRecord) => number;
  getEffectivePayment: (f: FarmerRecord) => number;
  onClose: () => void;
}

function DownloadConfirmModal({ farmers, tcb, getEffectiveSI, getEffectivePayment, onClose }: DownloadConfirmProps) {
  const [downloaded, setDownloaded] = useState(false);

  const csvLines = [
    "ROW_ID,FARMER_ID,INSURED_NAME,MUNICIPALITY,BARANGAY,FARM_ID,AREA_HA,PLANTED,PLANTING_DATE,GROWTH_STAGE,CROP_TYPE,SUM_INSURED_PHP,SIGNAL_NO,PERIOD_EXPOSURE_HRS,WIND_VEL_RANGE,INDEMNITY_FACTOR_PCT,INDEMNITY_PAYMENT_PHP",
    ...farmers.map(f => [
      f.rowId, f.farmerId, `"${f.insuredName}"`, f.municipality, f.barangay, f.farmId,
      f.areaHectare.toFixed(2), f.planted ? "YES" : "NO", f.plantingDate, f.growthStage, f.cropType,
      getEffectiveSI(f).toFixed(0), f.signalNo, f.periodOfExposure,
      f.windVelocityMin > 0 ? `${f.windVelocityMin}-${f.windVelocityMax}` : "0",
      f.indemnityFactor, Math.round(getEffectivePayment(f)),
    ].join(",")),
  ];
  const csvContent = csvLines.join("\n");
  const totalPay = farmers.reduce((s, f) => s + Math.round(getEffectivePayment(f)), 0);

  const handleDownload = () => {
    const uri = "data:text/csv;charset=utf-8," + encodeURIComponent(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", uri);
    link.setAttribute("download", `PCIC_Indemnification_${tcb.cycloneName.replace(/ /g,"_")}_${tcb.bulletinNo.replace(/ /g,"_")}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setDownloaded(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[480px] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Download size={15} className="text-[#166534]" />
            <p className="text-sm font-bold">Step 2 — Confirm Download</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
        </div>

        <div className="p-5 space-y-4">
          {downloaded ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
                <CheckCircle2 size={24} className="text-emerald-600" />
              </div>
              <p className="text-sm font-semibold text-emerald-700">CSV Downloaded Successfully</p>
              <p className="text-[11px] text-muted-foreground text-center">
                The indemnification report has been saved to your downloads folder.
              </p>
            </div>
          ) : (
            <>
              <div className="bg-muted/50 rounded-xl p-4 space-y-2 text-[11px]">
                <div className="flex justify-between"><span className="text-muted-foreground">Typhoon</span><span className="font-medium">{tcb.cycloneName}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">TCB Reference</span><span className="font-medium">{tcb.bulletinNo}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Signal Coverage</span><span className="font-medium text-amber-600">Signal No. 2</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Records</span><span className="font-medium">{farmers.length} farmers</span></div>
                <div className="flex justify-between border-t border-border pt-2 mt-2">
                  <span className="text-muted-foreground">Total Indemnity</span>
                  <span className="font-bold text-[#166534]">₱{totalPay.toLocaleString()}</span>
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground">
                File: <code className="bg-muted px-1 py-0.5 rounded text-[9px]">PCIC_Indemnification_{tcb.cycloneName.replace(/ /g,"_")}_{tcb.bulletinNo.replace(/ /g,"_")}.csv</code>
              </p>
            </>
          )}
        </div>

        <div className="flex gap-2 px-5 py-3 border-t border-border justify-end">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">
            {downloaded ? "Close" : "Cancel"}
          </button>
          {!downloaded && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
            >
              <Download size={12} /> Download CSV Now
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Module ─────────────────────────────────────────────────────────────
interface AssessmentModuleProps {
  darkMode: boolean;
  coverageRatePerHa: number;
}

const MUNICIPALITIES = ["All", "Naga City", "Pili", "Libmanan", "Sipocot", "Goa", "Lagonoy"];

export function AssessmentModule({ darkMode, coverageRatePerHa }: AssessmentModuleProps) {
  const [farmers] = useState<FarmerRecord[]>(mockFarmers);

  // Typhoon folder state
  const [openTyphoons, setOpenTyphoons] = useState<Set<string>>(new Set(["Pepito"]));
  const [selectedTCB, setSelectedTCB] = useState<TCBBulletin | null>(null);

  // Assessment state
  const [isCalculating, setIsCalculating] = useState(false);
  const [calculationDone, setCalculationDone] = useState(false);
  const [calcProgress, setCalcProgress] = useState(0);
  const [calcFailed, setCalcFailed] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [lastSuccessfulTCB, setLastSuccessfulTCB] = useState<TCBBulletin | null>(null);

  // Filters — default to Signal 2
  const [filterMuni, setFilterMuni] = useState("All");
  const [filterSignal, setFilterSignal] = useState<string>("2");
  const [sortField, setSortField] = useState<SortField>("rowId");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Coverage overrides
  const [coverageOverrides, setCoverageOverrides] = useState<Record<string, number>>({});
  const [editingCoverage, setEditingCoverage] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState<string>("");

  // CSV preview steps: null | "preview" | "confirm"
  const [csvStep, setCsvStep] = useState<null | "preview" | "confirm">(null);

  // Group bulletins by typhoon name
  const typhoonGroups = useMemo(() => {
    const groups: Record<string, TCBBulletin[]> = {};
    for (const b of mockBulletins) {
      if (!groups[b.cycloneName]) groups[b.cycloneName] = [];
      groups[b.cycloneName].push(b);
    }
    return groups;
  }, []);

  const toggleTyphoon = (name: string) => {
    setOpenTyphoons(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  // When TCB selected: auto-trigger calculation animation with simulated failure on Signal 3
  const handleSelectTCB = (tcb: TCBBulletin) => {
    if (selectedTCB?.id === tcb.id) return;
    setSelectedTCB(tcb);
    setCalculationDone(false);
    setCalcFailed(false);
    setCalcError(null);
    setIsCalculating(true);
    setCalcProgress(0);
    setFilterSignal("2");

    // Simulate a transient failure for Signal 3 bulletins to demonstrate rollback
    const willFail = tcb.signalNo >= 3 && Math.random() < 0.5;
    const failAt   = 45 + Math.random() * 20;

    let p = 0;
    const iv = setInterval(() => {
      p += Math.random() * 22 + 8;
      if (willFail && p >= failAt) {
        clearInterval(iv);
        setCalcProgress(Math.round(failAt));
        setTimeout(() => {
          setIsCalculating(false);
          setCalcFailed(true);
          setCalcError(
            `GEE SAR query timed out at ${Math.round(failAt)}% — Sentinel-1 tile coverage gap detected for Bulletin ${tcb.bulletinNo}. Assessment rolled back to last stable state.`
          );
          // Rollback: restore previous successful TCB
          setSelectedTCB(lastSuccessfulTCB);
          if (lastSuccessfulTCB) setCalculationDone(true);
        }, 300);
        return;
      }
      if (p >= 100) {
        p = 100;
        clearInterval(iv);
        setTimeout(() => {
          setIsCalculating(false);
          setCalculationDone(true);
          setLastSuccessfulTCB(tcb);
        }, 300);
      }
      setCalcProgress(Math.min(p, 100));
    }, 180);
  };

  const handleRetryCalc = () => {
    if (!selectedTCB) return;
    const tcb = selectedTCB;
    setCalcFailed(false);
    setCalcError(null);
    setCalculationDone(false);
    setIsCalculating(true);
    setCalcProgress(0);

    let p = 0;
    const iv = setInterval(() => {
      p += Math.random() * 22 + 8;
      if (p >= 100) {
        p = 100;
        clearInterval(iv);
        setTimeout(() => {
          setIsCalculating(false);
          setCalculationDone(true);
          setLastSuccessfulTCB(tcb);
        }, 300);
      }
      setCalcProgress(Math.min(p, 100));
    }, 180);
  };

  // Helpers
  const getEffectiveRate    = (f: FarmerRecord) => coverageOverrides[f.farmId] ?? coverageRatePerHa;
  const getEffectiveSI      = (f: FarmerRecord) => f.planted ? f.areaHectare * getEffectiveRate(f) : 0;
  const getEffectivePayment = (f: FarmerRecord) => getEffectiveSI(f) * (f.indemnityFactor / 100);

  const startCoverageEdit = (f: FarmerRecord) => { setEditingCoverage(f.farmId); setEditingValue(String(getEffectiveRate(f))); };
  const commitCoverageEdit = (farmId: string) => {
    const val = parseFloat(editingValue);
    if (!isNaN(val) && val > 0) setCoverageOverrides(o => ({ ...o, [farmId]: val }));
    setEditingCoverage(null);
  };

  const handleSort = (f: SortField) => {
    if (sortField === f) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(f); setSortDir("asc"); }
  };

  const filtered = useMemo(() => farmers
    .filter(f => filterMuni === "All" || f.municipality === filterMuni)
    .filter(f => filterSignal === "All" || f.signalNo === Number(filterSignal))
    .filter(f => f.planted)
    .sort((a, b) => {
      const va = a[sortField]; const vb = b[sortField];
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    }), [farmers, filterMuni, filterSignal, sortField, sortDir]);

  const signal2Planted = useMemo(() => farmers.filter(f => f.planted && f.signalNo === 2), [farmers]);

  const totalSI  = filtered.reduce((s, f) => s + getEffectiveSI(f), 0);
  const totalPay = filtered.reduce((s, f) => s + getEffectivePayment(f), 0);
  const totalArea = filtered.reduce((s, f) => s + f.areaHectare, 0);

  const muniChartData = MUNICIPALITIES.filter(m => m !== "All").map(m => ({
    name: m.replace(" City", ""),
    indemnity: signal2Planted.filter(f => f.municipality === m).reduce((s, f) => s + getEffectivePayment(f), 0) / 1000,
  }));

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field
      ? sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
      : <ArrowUpDown size={10} className="opacity-30" />;

  const signalBadge: Record<number, string> = {
    1: "bg-emerald-100 text-emerald-700 border-emerald-200",
    2: "bg-amber-100 text-amber-700 border-amber-200",
    3: "bg-red-100 text-red-700 border-red-200",
  };
  const stageColors: Record<string, string> = {
    Seedling: "text-green-700", Vegetative: "text-emerald-700",
    Reproductive: "text-yellow-700", Ripening: "text-amber-700",
  };

  return (
    <div className="h-full flex overflow-hidden bg-background">
      {/* ── Left: Typhoon Folder Panel ─────────────────────── */}
      <div className="w-56 shrink-0 flex flex-col border-r border-border bg-card overflow-hidden">
        <div className="px-3 py-2.5 border-b border-border">
          <div className="flex items-center gap-1.5">
            <FolderOpen size={13} className="text-[#166534]" />
            <p className="text-[11px] font-bold">Typhoon Events</p>
          </div>
          <p className="text-[9px] text-muted-foreground mt-0.5">Select a TCB to trigger assessment</p>
        </div>
        <div className="flex-1 overflow-auto py-1">
          {Object.entries(typhoonGroups).map(([typName, bulletins]) => {
            const isOpen = openTyphoons.has(typName);
            const highestSignal = Math.max(...bulletins.map(b => b.signalNo));
            return (
              <div key={typName} className="border-b border-border last:border-b-0">
                {/* Typhoon folder header */}
                <button
                  onClick={() => toggleTyphoon(typName)}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted/60 transition-colors text-left"
                >
                  {isOpen
                    ? <FolderOpen size={13} className="text-amber-500 shrink-0" />
                    : <Folder size={13} className="text-muted-foreground shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold truncate">Typhoon {typName}</p>
                    <p className="text-[9px] text-muted-foreground">{bulletins.length} bulletins</p>
                  </div>
                  <span className={`text-[9px] px-1 rounded border ${highestSignal >= 3 ? "bg-red-100 text-red-700 border-red-200" : highestSignal === 2 ? "bg-amber-100 text-amber-700 border-amber-200" : "bg-emerald-100 text-emerald-700 border-emerald-200"}`}>
                    S{highestSignal}
                  </span>
                  {isOpen ? <ChevronUp size={10} className="text-muted-foreground shrink-0" /> : <ChevronDown size={10} className="text-muted-foreground shrink-0" />}
                </button>

                {/* TCB bulletin list */}
                {isOpen && (
                  <div className="pl-3 pr-2 pb-2 space-y-1">
                    {bulletins.map(b => {
                      const isSelected = selectedTCB?.id === b.id;
                      return (
                        <button
                          key={b.id}
                          onClick={() => handleSelectTCB(b)}
                          className={`w-full text-left rounded-lg px-2.5 py-2 transition-all border ${
                            isSelected
                              ? "bg-[#166534] text-white border-[#166534]"
                              : "bg-background border-border hover:bg-muted/60"
                          }`}
                        >
                          <div className="flex items-center justify-between mb-0.5">
                            <span className={`text-[10px] font-bold ${isSelected ? "text-white" : ""}`}>{b.bulletinNo}</span>
                            <span className={`text-[9px] px-1 rounded border ${isSelected ? "bg-white/20 text-white border-white/30" : signalBadge[b.signalNo]}`}>
                              S{b.signalNo}
                            </span>
                          </div>
                          <p className={`text-[9px] ${isSelected ? "text-white/80" : "text-muted-foreground"}`}>{b.issueDateTime.slice(0, 10)}</p>
                          <p className={`text-[9px] font-medium mt-0.5 ${isSelected ? "text-white/90" : ""}`}>{b.windVelocityRange}</p>
                          <div className="flex items-center gap-1 mt-1">
                            <span className={`text-[8px] px-1 py-0.5 rounded ${isSelected ? "bg-white/20 text-white" : "bg-muted text-muted-foreground"}`}>
                              {b.status}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Signal 2 summary at bottom */}
        <div className="border-t border-border px-3 py-2 bg-muted/30 shrink-0">
          <p className="text-[9px] text-muted-foreground mb-1">Signal 2 Farms (Planted)</p>
          <p className="text-[13px] font-bold text-amber-600">{signal2Planted.length} farms</p>
          <p className="text-[9px] text-muted-foreground">₱{signal2Planted.reduce((s,f)=>s+getEffectivePayment(f),0).toLocaleString(undefined,{maximumFractionDigits:0})} est. indemnity</p>
        </div>
      </div>

      {/* ── Right: Main Content ─────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* CSV Modals */}
        {csvStep === "preview" && selectedTCB && (
          <CSVPreviewModal
            farmers={signal2Planted}
            tcb={selectedTCB}
            getEffectiveSI={getEffectiveSI}
            getEffectivePayment={getEffectivePayment}
            onClose={() => setCsvStep(null)}
            onConfirm={() => setCsvStep("confirm")}
          />
        )}
        {csvStep === "confirm" && selectedTCB && (
          <DownloadConfirmModal
            farmers={signal2Planted}
            tcb={selectedTCB}
            getEffectiveSI={getEffectiveSI}
            getEffectivePayment={getEffectivePayment}
            onClose={() => setCsvStep(null)}
          />
        )}

        {/* Top bar */}
        <div className="flex items-center gap-3 px-4 py-2 bg-card border-b border-border shrink-0 flex-wrap gap-y-1">
          <div className="flex items-center gap-2">
            <Calculator size={14} className="text-[#166534]" />
            <span className="text-sm font-semibold">Assessment & Reporting</span>
            {selectedTCB && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                {selectedTCB.cycloneName} · {selectedTCB.bulletinNo}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 ml-auto flex-wrap gap-y-1">
            <select
              value={filterMuni}
              onChange={e => setFilterMuni(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {MUNICIPALITIES.map(m => <option key={m}>{m}</option>)}
            </select>
            <select
              value={filterSignal}
              onChange={e => setFilterSignal(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {["2", "1", "3", "All"].map(s => (
                <option key={s} value={s}>{s === "All" ? "All Signals" : `Signal ${s}${s === "2" ? " (Default)" : ""}`}</option>
              ))}
            </select>
            <button
              onClick={() => setCsvStep("preview")}
              disabled={!calculationDone}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#166534] text-white text-[11px] font-medium hover:bg-[#14532d] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Eye size={11} /> Review & Generate Report
            </button>
          </div>
        </div>

        {/* Coverage rate banner */}
        <div className="flex items-center gap-2 px-4 py-1 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-100 shrink-0">
          <span className="text-[10px] text-amber-700">
            RSBSA Coverage Rate: <strong>₱{coverageRatePerHa.toLocaleString()}/ha</strong>
            {Object.keys(coverageOverrides).length > 0 && (
              <span className="ml-2 text-[9px]">· {Object.keys(coverageOverrides).length} row override(s)</span>
            )}
            <span className="ml-2 text-[9px] text-amber-500">— Hover Sum Insured cell to edit per-farm rate</span>
          </span>
        </div>

        {/* Empty state if no TCB selected */}
        {!selectedTCB && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
            <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center">
              <Wind size={28} className="text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-semibold">Select a TCB Bulletin</p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Click a bulletin from the typhoon folder on the left.<br />
                The assessment will automatically calculate based on Signal No. 2 farms.
              </p>
            </div>
          </div>
        )}

        {/* Calculation progress */}
        {isCalculating && (
          <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-200 shrink-0">
            <Loader size={13} className="text-[#1e3a5f] animate-spin shrink-0" />
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] text-[#1e3a5f] font-medium">
                  Running assessment — cross-referencing {selectedTCB?.bulletinNo} exposure data with crop stages…
                </span>
                <span className="text-[10px] text-[#1e3a5f] font-bold">{Math.round(calcProgress)}%</span>
              </div>
              <div className="w-full h-1.5 bg-blue-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#1e3a5f] rounded-full transition-all duration-200"
                  style={{ width: `${calcProgress}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Failure / rollback banner */}
        {calcFailed && !isCalculating && (
          <div className="flex items-start gap-3 px-4 py-3 bg-red-50 dark:bg-red-950/30 border-b border-red-200 shrink-0">
            <AlertCircle size={14} className="text-red-600 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-red-700">Assessment Failed — Automatic Rollback Applied</p>
              <p className="text-[10px] text-red-600 mt-0.5">{calcError}</p>
              {lastSuccessfulTCB && (
                <p className="text-[10px] text-red-500 mt-0.5">
                  System restored to last stable assessment: <strong>{lastSuccessfulTCB.bulletinNo}</strong>
                </p>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={handleRetryCalc}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-600 text-white text-[10px] font-semibold hover:bg-red-700 transition-colors"
              >
                <RefreshCw size={10} /> Retry
              </button>
              <button
                onClick={() => { setCalcFailed(false); setCalcError(null); }}
                className="px-2.5 py-1.5 rounded-lg border border-red-200 text-red-600 text-[10px] hover:bg-red-100 transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {calculationDone && !isCalculating && selectedTCB && (
          <>
            <div className="flex items-center gap-2 px-4 py-1.5 bg-emerald-50 dark:bg-emerald-950/30 border-b border-emerald-200 shrink-0">
              <CheckCircle2 size={11} className="text-emerald-600 shrink-0" />
              <span className="text-[10px] text-emerald-700">
                Assessment complete for <strong>{selectedTCB.bulletinNo}</strong> — {signal2Planted.length} Signal No. 2 planted records calculated using PCIC damage factors.
              </span>
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-5 gap-2.5 p-3 shrink-0">
              {[
                { label: "Filtered Records",   value: filtered.length,                            unit: "",   color: "#1e3a5f" },
                { label: "Signal 2 Planted",   value: signal2Planted.length,                      unit: "",   color: "#ca8a04" },
                { label: "Total Area",          value: totalArea.toFixed(1),                       unit: "ha", color: "#166534" },
                { label: "Total Sum Insured",   value: `₱${(totalSI / 1000).toFixed(0)}K`,         unit: "",   color: "#ca8a04" },
                { label: "Total Indemnity",     value: `₱${(totalPay / 1000).toFixed(0)}K`,        unit: "",   color: "#ef4444" },
              ].map((s, i) => (
                <div key={i} className="bg-card border border-border rounded-xl px-3 py-2">
                  <p className="text-[9px] text-muted-foreground uppercase tracking-wide">{s.label}</p>
                  <p className="text-lg font-bold mt-0.5" style={{ color: s.color }}>
                    {s.value}<span className="text-xs text-muted-foreground ml-0.5">{s.unit}</span>
                  </p>
                </div>
              ))}
            </div>

            {/* Table + Chart */}
            <div className="flex flex-1 overflow-hidden">
              {/* Table */}
              <div className="flex-1 overflow-auto">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-[#1e3a5f] text-white">
                      {([
                        { l: "#",          f: "rowId"           },
                        { l: "Farmer ID",  f: "farmerId"        },
                        { l: "Name",       f: "insuredName"     },
                        { l: "Muni.",      f: "municipality"    },
                        { l: "Farm ID",    f: "farmId"          },
                        { l: "Area",       f: "areaHectare"     },
                        { l: "Stage",      f: "growthStage"     },
                        { l: "Signal",     f: "signalNo"        },
                        { l: "Exp (h)",    f: "periodOfExposure"},
                        { l: "Wind (kph)", f: "windVelocityMin" },
                        { l: "Sum Ins.",   f: "sumInsured"      },
                        { l: "Ind. %",     f: "indemnityFactor" },
                        { l: "Payment",    f: "indemnityPayment"},
                      ] as { l: string; f: SortField }[]).map(col => (
                        <th
                          key={col.f}
                          className="px-2 py-1.5 text-left font-semibold cursor-pointer hover:bg-white/10 whitespace-nowrap"
                          onClick={() => handleSort(col.f)}
                        >
                          <span className="flex items-center gap-0.5">{col.l}<SortIcon field={col.f} /></span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((f, i) => (
                      <tr key={f.farmId} className={`border-t border-border hover:bg-muted/40 transition-colors ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                        <td className="px-2 py-1.5 text-muted-foreground">{f.rowId}</td>
                        <td className="px-2 py-1.5 font-mono text-[9px]">{f.farmerId.slice(-5)}</td>
                        <td className="px-2 py-1.5 font-medium whitespace-nowrap">{f.insuredName}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{f.municipality}</td>
                        <td className="px-2 py-1.5 font-mono text-[#166534]">{f.farmId}</td>
                        <td className="px-2 py-1.5 text-right">{f.areaHectare.toFixed(2)}</td>
                        <td className={`px-2 py-1.5 font-medium ${stageColors[f.growthStage]}`}>{f.growthStage}</td>
                        <td className="px-2 py-1.5">
                          <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${signalBadge[f.signalNo]}`}>
                            S{f.signalNo}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right">{f.periodOfExposure > 0 ? f.periodOfExposure : "—"}</td>
                        <td className="px-2 py-1.5 text-right text-muted-foreground">
                          {f.windVelocityMin > 0 ? `${f.windVelocityMin}–${f.windVelocityMax}` : "—"}
                        </td>
                        {/* Editable Sum Insured */}
                        <td className="px-2 py-1.5 text-right">
                          {editingCoverage === f.farmId ? (
                            <div className="flex items-center gap-1 justify-end">
                              <span className="text-[9px] text-muted-foreground">₱/ha</span>
                              <input
                                autoFocus
                                type="number"
                                value={editingValue}
                                onChange={e => setEditingValue(e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter") commitCoverageEdit(f.farmId); if (e.key === "Escape") setEditingCoverage(null); }}
                                className="w-20 border border-[#166534] rounded px-1.5 py-0.5 text-[10px] bg-background focus:outline-none text-right"
                              />
                              <button onClick={() => commitCoverageEdit(f.farmId)} className="text-emerald-600 hover:text-emerald-700"><Check size={10} /></button>
                              <button onClick={() => setEditingCoverage(null)} className="text-muted-foreground hover:text-foreground"><X size={10} /></button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-1 justify-end group">
                              <span className={getEffectiveRate(f) !== coverageRatePerHa ? "text-amber-600 font-bold" : ""}>
                                ₱{getEffectiveSI(f).toLocaleString()}
                              </span>
                              <button
                                onClick={() => startCoverageEdit(f)}
                                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-[#166534] transition-opacity"
                                title="Edit coverage rate"
                              >
                                <Pencil size={9} />
                              </button>
                            </div>
                          )}
                        </td>
                        <td className={`px-2 py-1.5 text-right font-bold ${f.indemnityFactor >= 50 ? "text-red-600" : f.indemnityFactor >= 30 ? "text-amber-600" : "text-emerald-600"}`}>
                          {f.indemnityFactor > 0 ? `${f.indemnityFactor}%` : "—"}
                        </td>
                        <td className="px-2 py-1.5 text-right font-bold text-[#166534]">
                          ₱{Math.round(getEffectivePayment(f)).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-[#166534]/10 border-t-2 border-[#166534] font-bold text-[11px]">
                      <td colSpan={5} className="px-2 py-2">TOTAL ({filtered.length} records)</td>
                      <td className="px-2 py-2 text-right">{totalArea.toFixed(2)}</td>
                      <td colSpan={5} />
                      <td className="px-2 py-2 text-right text-[#166534]">₱{totalSI.toLocaleString()}</td>
                      <td />
                      <td className="px-2 py-2 text-right text-[#166534]">₱{Math.round(totalPay).toLocaleString()}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              {/* Right: Chart */}
              <div className="w-52 shrink-0 flex flex-col border-l border-border overflow-hidden">
                <div className="px-3 py-2 border-b border-border bg-card shrink-0">
                  <p className="text-[11px] font-semibold">Indemnity by Municipality</p>
                  <p className="text-[9px] text-muted-foreground">Signal 2 farms only</p>
                </div>
                <div className="flex-1 overflow-auto p-2">
                  <ResponsiveContainer width="100%" height={190}>
                    <BarChart data={muniChartData} layout="vertical" barSize={11}>
                      <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#1c2e1c" : "#e5e7eb"} horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} tickFormatter={v => `₱${v.toFixed(0)}K`} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} axisLine={false} tickLine={false} width={46} />
                      <RTooltip
                        contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border: "1px solid #ccc", borderRadius: 6, fontSize: 10 }}
                        formatter={(v: number) => [`₱${v.toFixed(1)}K`, ""]}
                      />
                      <Bar dataKey="indemnity" name="Indemnity (₱K)" fill="#ca8a04" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>

                  {/* Damage Factor Table */}
                  <div className="mt-3">
                    <p className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Damage Factors</p>
                    <table className="w-full text-[9px]">
                      <thead>
                        <tr className="bg-muted/60 text-muted-foreground">
                          <th className="px-1.5 py-1 text-left">Stage</th>
                          <th className="px-1.5 py-1 text-center">S1</th>
                          <th className="px-1.5 py-1 text-center text-amber-600">S2</th>
                          <th className="px-1.5 py-1 text-center">S3</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(["Seedling", "Vegetative", "Reproductive", "Ripening"] as const).map(s => (
                          <tr key={s} className="border-t border-border">
                            <td className="px-1.5 py-1">{s.slice(0, 5)}</td>
                            <td className="px-1.5 py-1 text-center text-emerald-600">{DAMAGE_FACTORS[s][1]}%</td>
                            <td className="px-1.5 py-1 text-center text-amber-600 font-bold bg-amber-50 dark:bg-amber-950/20">{DAMAGE_FACTORS[s][2]}%</td>
                            <td className="px-1.5 py-1 text-center text-red-600">{DAMAGE_FACTORS[s][3]}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
