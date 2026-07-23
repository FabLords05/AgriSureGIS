import { useState, useMemo, useEffect } from "react";
import {
  Download, Eye, ChevronDown, ChevronUp, ArrowUpDown,
  CheckCircle2, Loader, Calculator,
  FolderOpen, Folder, AlertCircle, Wind, RefreshCw
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import {
  getBulletins, calculateAssessments, getAssessments, getFarms, getAssessmentsExportUrl,
  Bulletin, Assessment, Farm,
} from "@/lib/api";

interface AssessmentRow extends Farm {
  assessment: Assessment | null;
}

type SortField = "farm_id" | "farmer_name" | "municipality" | "area_size" | "period_of_exposure" | "amount_cover" | "indemnity_factor" | "final_indemnity_payment";
type SortDir = "asc" | "desc";

function sortValue(row: AssessmentRow, field: SortField): string | number {
  switch (field) {
    case "farm_id": return row.farm_id;
    case "farmer_name": return row.farmer_name ?? "";
    case "municipality": return row.municipality ?? "";
    case "area_size": return row.area_size ?? 0;
    case "period_of_exposure": return row.assessment?.period_of_exposure ?? 0;
    case "amount_cover": return row.assessment?.amount_cover ?? 0;
    case "indemnity_factor": return row.assessment?.indemnity_factor ?? 0;
    case "final_indemnity_payment": return row.assessment?.final_indemnity_payment ?? 0;
  }
}

// ─── CSV Preview / Download Modal ────────────────────────────────────────────
interface CSVPreviewProps {
  rows: AssessmentRow[];
  bulletin: Bulletin;
  onClose: () => void;
}

function CSVPreviewModal({ rows, bulletin, onClose }: CSVPreviewProps) {
  const HEADERS = ["Farm ID", "Farmer", "Municipality", "Barangay", "Area (ha)", "Crop Stage", "Signal", "Exp (h)", "Sum Insured", "Ind. Factor", "Indemnity Payment"];
  const totalCover = rows.reduce((s, r) => s + (r.assessment?.amount_cover ?? 0), 0);
  const totalPay = rows.reduce((s, r) => s + (r.assessment?.final_indemnity_payment ?? 0), 0);

  const handleDownload = () => {
    window.open(getAssessmentsExportUrl(bulletin.typhoon_id), "_blank");
  };

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
              <p className="text-sm font-bold">Review CSV Before Downloading</p>
              <p className="text-[10px] text-muted-foreground">
                PCIC Indemnification Report · {bulletin.typhoon_name} · {bulletin.title}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        {/* Alert bar */}
        <div className="flex items-center gap-2 px-5 py-2 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-100 shrink-0">
          <AlertCircle size={11} className="text-blue-600 shrink-0" />
          <p className="text-[10px] text-blue-700 dark:text-blue-300">
            These {rows.length} computed records are exactly what the downloaded CSV will contain, scoped to this typhoon.
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
              {rows.map((r, i) => (
                <tr key={r.farm_id} className={`border-t border-border hover:bg-muted/30 ${i % 2 === 0 ? "bg-card" : "bg-muted/10"}`}>
                  <td className="px-2 py-1.5 font-mono text-[#166534]">#{r.farm_id}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">{r.farmer_name ?? "—"}</td>
                  <td className="px-2 py-1.5">{r.municipality ?? "—"}</td>
                  <td className="px-2 py-1.5">{r.barangay ?? "—"}</td>
                  <td className="px-2 py-1.5 text-right">{r.area_size != null ? r.area_size.toFixed(2) : "—"}</td>
                  <td className="px-2 py-1.5">{r.assessment?.crop_stage ?? "—"}</td>
                  <td className="px-2 py-1.5 text-center font-bold text-amber-600">{r.assessment?.wind_velocity != null ? `S${r.assessment.wind_velocity}` : "—"}</td>
                  <td className="px-2 py-1.5 text-center">{r.assessment?.period_of_exposure ?? "—"}</td>
                  <td className="px-2 py-1.5 text-right font-medium">{r.assessment?.amount_cover != null ? `₱${r.assessment.amount_cover.toLocaleString()}` : "—"}</td>
                  <td className="px-2 py-1.5 text-right font-bold text-amber-600">{r.assessment?.indemnity_factor != null ? `${r.assessment.indemnity_factor}%` : "—"}</td>
                  <td className="px-2 py-1.5 text-right font-bold text-[#166534]">{r.assessment ? `₱${Math.round(r.assessment.final_indemnity_payment).toLocaleString()}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-border bg-muted/20 shrink-0">
          <div className="flex items-center gap-6 text-[11px]">
            <span className="text-muted-foreground"><strong className="text-foreground">{rows.length}</strong> records</span>
            <span className="text-muted-foreground">Total Sum Insured: <strong className="text-[#ca8a04]">₱{totalCover.toLocaleString()}</strong></span>
            <span className="text-muted-foreground">Total Indemnity: <strong className="text-[#166534]">₱{Math.round(totalPay).toLocaleString()}</strong></span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">
              Cancel
            </button>
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
            >
              <Download size={12} /> Download CSV
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Module ─────────────────────────────────────────────────────────────
interface AssessmentModuleProps {
  darkMode: boolean;
  selectedBulletin: Bulletin | null;
  onSelectBulletin: (bulletin: Bulletin | null) => void;
}

const signalColors: Record<number, string> = {
  2: "text-amber-600 font-bold", 3: "text-orange-600 font-bold", 4: "text-red-600 font-bold", 5: "text-red-800 font-bold",
};

export function AssessmentModule({ darkMode, selectedBulletin, onSelectBulletin }: AssessmentModuleProps) {
  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [openTyphoons, setOpenTyphoons] = useState<Set<string>>(new Set());

  const [isCalculating, setIsCalculating] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [assessmentsComputed, setAssessmentsComputed] = useState<number | null>(null);

  const [farms, setFarms] = useState<Farm[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [isLoadingResults, setIsLoadingResults] = useState(false);

  const [filterMuni, setFilterMuni] = useState("All");
  const [filterSignal, setFilterSignal] = useState<string>("All");
  const [sortField, setSortField] = useState<SortField>("farm_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const [showCsvPreview, setShowCsvPreview] = useState(false);

  useEffect(() => {
    getBulletins().then(setBulletins).catch(() => setBulletins([]));
  }, []);

  const typhoonGroups = useMemo(() => {
    const groups: Record<string, Bulletin[]> = {};
    for (const b of bulletins) {
      if (!groups[b.typhoon_name]) groups[b.typhoon_name] = [];
      groups[b.typhoon_name].push(b);
    }
    return groups;
  }, [bulletins]);

  const toggleTyphoon = (name: string) => {
    setOpenTyphoons(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const loadResults = (typhoonId: number) => {
    setIsLoadingResults(true);
    Promise.all([getAssessments(typhoonId), getFarms()])
      .then(([assessmentsRes, farmsRes]) => {
        setAssessments(assessmentsRes.data);
        setFarms(farmsRes.data);
      })
      .catch(() => setAssessments([]))
      .finally(() => setIsLoadingResults(false));
  };

  const runCalculation = (bulletin: Bulletin) => {
    setIsCalculating(true);
    setCalcError(null);
    setAssessmentsComputed(null);
    calculateAssessments(bulletin.typhoon_id, bulletin.tcb_id)
      .then(result => {
        setAssessmentsComputed(result.assessments_computed);
        loadResults(bulletin.typhoon_id);
      })
      .catch(error => setCalcError(error instanceof Error ? error.message : "Failed to calculate assessments."))
      .finally(() => setIsCalculating(false));
  };

  useEffect(() => {
    if (!selectedBulletin) {
      setAssessmentsComputed(null);
      setCalcError(null);
      return;
    }
    runCalculation(selectedBulletin);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBulletin?.tcb_id]);

  const assessmentByFarmId = useMemo(() => {
    const map = new Map<number, Assessment>();
    for (const a of assessments) {
      if (a.farm_id != null && !map.has(a.farm_id)) map.set(a.farm_id, a);
    }
    return map;
  }, [assessments]);

  const assessedRows: AssessmentRow[] = useMemo(
    () => farms
      .map(f => ({ ...f, assessment: assessmentByFarmId.get(f.farm_id) ?? null }))
      .filter((r): r is AssessmentRow => r.assessment != null),
    [farms, assessmentByFarmId]
  );

  const municipalities = useMemo(() => {
    const set = new Set(assessedRows.map(r => r.municipality).filter((m): m is string => !!m));
    return ["All", ...Array.from(set).sort()];
  }, [assessedRows]);

  const filtered = useMemo(() => assessedRows
    .filter(r => filterMuni === "All" || r.municipality === filterMuni)
    .filter(r => filterSignal === "All" || r.assessment?.wind_velocity === Number(filterSignal))
    .sort((a, b) => {
      const va = sortValue(a, sortField);
      const vb = sortValue(b, sortField);
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    }), [assessedRows, filterMuni, filterSignal, sortField, sortDir]);

  const handleSort = (f: SortField) => {
    if (sortField === f) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(f); setSortDir("asc"); }
  };

  const totalArea = filtered.reduce((s, r) => s + (r.area_size ?? 0), 0);
  const totalCover = filtered.reduce((s, r) => s + (r.assessment?.amount_cover ?? 0), 0);
  const totalPay = filtered.reduce((s, r) => s + (r.assessment?.final_indemnity_payment ?? 0), 0);

  const muniChartData = useMemo(() => {
    const totals = new Map<string, number>();
    for (const r of filtered) {
      const key = r.municipality ?? "Unknown";
      totals.set(key, (totals.get(key) ?? 0) + (r.assessment?.final_indemnity_payment ?? 0));
    }
    return Array.from(totals.entries()).map(([name, indemnity]) => ({ name, indemnity: indemnity / 1000 }));
  }, [filtered]);

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field
      ? sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
      : <ArrowUpDown size={10} className="opacity-30" />;

  return (
    <div className="h-full flex overflow-hidden bg-background">
      {/* CSV Modal */}
      {showCsvPreview && selectedBulletin && (
        <CSVPreviewModal
          rows={filtered}
          bulletin={selectedBulletin}
          onClose={() => setShowCsvPreview(false)}
        />
      )}

      {/* ── Left: Typhoon Folder Panel ─────────────────────── */}
      <div className="w-56 shrink-0 flex flex-col border-r border-border bg-card overflow-hidden">
        <div className="px-3 py-2.5 border-b border-border">
          <div className="flex items-center gap-1.5">
            <FolderOpen size={13} className="text-[#166534]" />
            <p className="text-[11px] font-bold">Typhoon Events</p>
          </div>
          <p className="text-[9px] text-muted-foreground mt-0.5">Select a TCB to run the assessment</p>
        </div>
        <div className="flex-1 overflow-auto py-1">
          {Object.entries(typhoonGroups).map(([typName, tBulletins]) => {
            const isOpen = openTyphoons.has(typName);
            return (
              <div key={typName} className="border-b border-border last:border-b-0">
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
                    <p className="text-[9px] text-muted-foreground">{tBulletins.length} bulletins</p>
                  </div>
                  {isOpen ? <ChevronUp size={10} className="text-muted-foreground shrink-0" /> : <ChevronDown size={10} className="text-muted-foreground shrink-0" />}
                </button>

                {isOpen && (
                  <div className="pl-3 pr-2 pb-2 space-y-1">
                    {tBulletins.map(b => {
                      const isSelected = selectedBulletin?.tcb_id === b.tcb_id;
                      return (
                        <button
                          key={b.tcb_id}
                          onClick={() => onSelectBulletin(isSelected ? null : b)}
                          className={`w-full text-left rounded-lg px-2.5 py-2 transition-all border ${
                            isSelected ? "bg-[#166534] text-white border-[#166534]" : "bg-background border-border hover:bg-muted/60"
                          }`}
                        >
                          <p className={`text-[10px] font-bold ${isSelected ? "text-white" : ""}`}>{b.title}</p>
                          <p className={`text-[9px] ${isSelected ? "text-white/80" : "text-muted-foreground"}`}>{b.issued_at ?? "Unknown date"}</p>
                          <p className={`text-[9px] font-medium mt-0.5 ${isSelected ? "text-white/90" : ""}`}>
                            {b.category ?? "Unknown"} · {b.max_sustained_winds ?? "—"} km/h
                          </p>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Right: Main Content ─────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <div className="flex items-center gap-3 px-4 py-2 bg-card border-b border-border shrink-0 flex-wrap gap-y-1">
          <div className="flex items-center gap-2">
            <Calculator size={14} className="text-[#166534]" />
            <span className="text-sm font-semibold">Assessment & Reporting</span>
            {selectedBulletin && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200">
                {selectedBulletin.typhoon_name} · {selectedBulletin.title}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 ml-auto flex-wrap gap-y-1">
            <select
              value={filterMuni}
              onChange={e => setFilterMuni(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {municipalities.map(m => <option key={m}>{m}</option>)}
            </select>
            <select
              value={filterSignal}
              onChange={e => setFilterSignal(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {["All", "2", "3", "4", "5"].map(s => (
                <option key={s} value={s}>{s === "All" ? "All Signals" : `Signal ${s}`}</option>
              ))}
            </select>
            <button
              onClick={() => setShowCsvPreview(true)}
              disabled={filtered.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#166534] text-white text-[11px] font-medium hover:bg-[#14532d] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Eye size={11} /> Review & Export CSV
            </button>
          </div>
        </div>

        {/* Empty state if no TCB selected */}
        {!selectedBulletin && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
            <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center">
              <Wind size={28} className="text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-semibold">Select a TCB Bulletin</p>
              <p className="text-[11px] text-muted-foreground mt-1">
                Click a bulletin from the typhoon folder on the left.<br />
                The assessment will run against real eligibility rules (signal ≥ 2, exposure ≥ 6h).
              </p>
            </div>
          </div>
        )}

        {/* Calculation in progress */}
        {isCalculating && (
          <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-200 shrink-0">
            <Loader size={13} className="text-[#1e3a5f] animate-spin shrink-0" />
            <span className="text-[11px] text-[#1e3a5f] font-medium">
              Running assessment for {selectedBulletin?.title}…
            </span>
          </div>
        )}

        {/* Real error banner */}
        {calcError && !isCalculating && (
          <div className="flex items-start gap-3 px-4 py-3 bg-red-50 dark:bg-red-950/30 border-b border-red-200 shrink-0">
            <AlertCircle size={14} className="text-red-600 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-semibold text-red-700">Assessment Failed</p>
              <p className="text-[10px] text-red-600 mt-0.5">{calcError}</p>
            </div>
            <button
              onClick={() => selectedBulletin && runCalculation(selectedBulletin)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-red-600 text-white text-[10px] font-semibold hover:bg-red-700 transition-colors shrink-0"
            >
              <RefreshCw size={10} /> Retry
            </button>
          </div>
        )}

        {/* Honest zero-result banner */}
        {!isCalculating && !calcError && assessmentsComputed === 0 && (
          <div className="flex items-center gap-2 px-4 py-1.5 bg-muted/50 border-b border-border shrink-0">
            <AlertCircle size={11} className="text-muted-foreground shrink-0" />
            <span className="text-[10px] text-muted-foreground">
              0 assessments computed — no policies met eligibility criteria (signal ≥ 2, exposure ≥ 6h, crop stage in Booting/Flowering/Maturity) for this bulletin.
            </span>
          </div>
        )}

        {!isCalculating && !calcError && assessmentsComputed !== null && assessmentsComputed > 0 && selectedBulletin && (
          <>
            <div className="flex items-center gap-2 px-4 py-1.5 bg-emerald-50 dark:bg-emerald-950/30 border-b border-emerald-200 shrink-0">
              <CheckCircle2 size={11} className="text-emerald-600 shrink-0" />
              <span className="text-[10px] text-emerald-700">
                Assessment complete for <strong>{selectedBulletin.title}</strong> — {assessmentsComputed} record(s) computed using real PCIC damage factors.
              </span>
              {isLoadingResults && <span className="text-[10px] text-muted-foreground">Loading results…</span>}
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-4 gap-2.5 p-3 shrink-0">
              {[
                { label: "Filtered Records", value: filtered.length, unit: "", color: "#1e3a5f" },
                { label: "Total Area", value: totalArea.toFixed(1), unit: "ha", color: "#166534" },
                { label: "Total Sum Insured", value: `₱${(totalCover / 1000).toFixed(0)}K`, unit: "", color: "#ca8a04" },
                { label: "Total Indemnity", value: `₱${(totalPay / 1000).toFixed(0)}K`, unit: "", color: "#ef4444" },
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
              <div className="flex-1 overflow-auto">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-[#1e3a5f] text-white">
                      {([
                        { l: "Farm ID", f: "farm_id" },
                        { l: "Farmer", f: "farmer_name" },
                        { l: "Muni.", f: "municipality" },
                        { l: "Area", f: "area_size" },
                        { l: "Exp (h)", f: "period_of_exposure" },
                        { l: "Sum Ins.", f: "amount_cover" },
                        { l: "Ind. %", f: "indemnity_factor" },
                        { l: "Payment", f: "final_indemnity_payment" },
                      ] as { l: string; f: SortField }[]).map(col => (
                        <th
                          key={col.f}
                          className="px-2 py-1.5 text-left font-semibold cursor-pointer hover:bg-white/10 whitespace-nowrap"
                          onClick={() => handleSort(col.f)}
                        >
                          <span className="flex items-center gap-0.5">{col.l}<SortIcon field={col.f} /></span>
                        </th>
                      ))}
                      <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Stage</th>
                      <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((r, i) => (
                      <tr key={r.farm_id} className={`border-t border-border hover:bg-muted/40 transition-colors ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                        <td className="px-2 py-1.5 font-mono text-[#166534]">#{r.farm_id}</td>
                        <td className="px-2 py-1.5 font-medium whitespace-nowrap">{r.farmer_name ?? "—"}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{r.municipality ?? "—"}</td>
                        <td className="px-2 py-1.5 text-right">{r.area_size != null ? r.area_size.toFixed(2) : "—"}</td>
                        <td className="px-2 py-1.5 text-right">{r.assessment?.period_of_exposure ?? "—"}</td>
                        <td className="px-2 py-1.5 text-right">{r.assessment?.amount_cover != null ? `₱${r.assessment.amount_cover.toLocaleString()}` : "—"}</td>
                        <td className={`px-2 py-1.5 text-right font-bold ${(r.assessment?.indemnity_factor ?? 0) >= 50 ? "text-red-600" : (r.assessment?.indemnity_factor ?? 0) >= 30 ? "text-amber-600" : "text-emerald-600"}`}>
                          {r.assessment?.indemnity_factor != null ? `${r.assessment.indemnity_factor}%` : "—"}
                        </td>
                        <td className="px-2 py-1.5 text-right font-bold text-[#166534]">
                          {r.assessment ? `₱${Math.round(r.assessment.final_indemnity_payment).toLocaleString()}` : "—"}
                        </td>
                        <td className="px-2 py-1.5">{r.assessment?.crop_stage ?? "—"}</td>
                        <td className="px-2 py-1.5">
                          {r.assessment?.wind_velocity != null ? (
                            <span className={signalColors[r.assessment.wind_velocity] ?? ""}>S{r.assessment.wind_velocity}</span>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-[#166534]/10 border-t-2 border-[#166534] font-bold text-[11px]">
                      <td colSpan={3} className="px-2 py-2">TOTAL ({filtered.length} records)</td>
                      <td className="px-2 py-2 text-right">{totalArea.toFixed(2)}</td>
                      <td />
                      <td className="px-2 py-2 text-right text-[#166534]">₱{totalCover.toLocaleString()}</td>
                      <td />
                      <td className="px-2 py-2 text-right text-[#166534]">₱{Math.round(totalPay).toLocaleString()}</td>
                      <td colSpan={2} />
                    </tr>
                  </tfoot>
                </table>
              </div>

              {/* Right: Chart */}
              <div className="w-52 shrink-0 flex flex-col border-l border-border overflow-hidden">
                <div className="px-3 py-2 border-b border-border bg-card shrink-0">
                  <p className="text-[11px] font-semibold">Indemnity by Municipality</p>
                  <p className="text-[9px] text-muted-foreground">Current filter selection</p>
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
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
