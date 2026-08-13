import { useState, useMemo, useEffect } from "react";
import { toast } from "sonner";
import {
  Download, Eye, ChevronDown, ChevronUp, ArrowUpDown,
  FileSpreadsheet, RefreshCw, AlertCircle, Calculator, MapPin,
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import {
  getAssessmentsPabsSummary, getAssessmentsExportPabsUrl, getBulletins, getTyphoonSummary, calculateAssessments,
  getBulletinSignals,
  PabsAssessmentRow, Bulletin, TyphoonSummary, TyphoonSummaryArea, TcbSignal,
} from "@/lib/api";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

type SortField = "FARMER_NAME" | "municipality" | "TYPHOON_NAME" | "AREA" | "PERIOD_OF_EXPOSURE" | "WIND_VELOCITY" | "AC";
type SortDir = "asc" | "desc";

const PABS_HEADERS: { label: string; field: keyof PabsAssessmentRow }[] = [
  { label: "Farmer Name", field: "FARMER_NAME" },
  { label: "Farmer ID", field: "FARMERID" },
  { label: "Farm ID", field: "FARMID" },
  { label: "IRID", field: "IRID" },
  { label: "Area", field: "AREA" },
  { label: "Typhoon", field: "TYPHOON_NAME" },
  { label: "Exposure (h)", field: "PERIOD_OF_EXPOSURE" },
  { label: "Wind Velocity", field: "WIND_VELOCITY" },
  { label: "Date Filed", field: "DATE_FILED" },
  { label: "Date of Occurrence", field: "DATE_OF_OCCURRENCE" },
  { label: "P", field: "P" },
  { label: "S", field: "S" },
  { label: "AC", field: "AC" },
  { label: "Remarks", field: "REMARKS" },
];

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

// Matches the CSV export's float_format="%.2f" -- what the preview shows for
// AREA/AC must be exactly what ends up in the downloaded file.
function formatPabsCell(field: keyof PabsAssessmentRow, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if ((field === "AREA" || field === "AC") && typeof value === "number") {
    return value.toFixed(2);
  }
  return String(value);
}

// ─── CSV Preview / Download Modal ────────────────────────────────────────────
function CSVPreviewModal({ rows, onClose }: { rows: PabsAssessmentRow[]; onClose: () => void }) {
  const totalArea = rows.reduce((s, r) => s + (r.AREA ?? 0), 0);
  const totalAC = rows.reduce((s, r) => s + (r.AC ?? 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[95vw] max-w-7xl max-h-[88vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#166534]/10 flex items-center justify-center">
              <Eye size={15} className="text-[#166534]" />
            </div>
            <div>
              <p className="text-sm font-bold">Review CSV Before Downloading</p>
              <p className="text-[10px] text-muted-foreground">PABS Indemnity Computation Format · All typhoons combined</p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        <div className="flex items-center gap-2 px-5 py-2 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-100 shrink-0">
          <AlertCircle size={11} className="text-blue-600 shrink-0" />
          <p className="text-[10px] text-blue-700 dark:text-blue-300">
            These {rows.length} records are exactly what the downloaded CSV will contain. IRID, P, S, and Remarks are blank — no data source for those columns yet.
          </p>
        </div>

        <div className="overflow-auto flex-1 px-1">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#166534] text-white">
                {PABS_HEADERS.map(h => (
                  <th key={h.field} className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">{h.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.assessment_id} className={`border-t border-border hover:bg-muted/30 ${i % 2 === 0 ? "bg-card" : "bg-muted/10"}`}>
                  {PABS_HEADERS.map(h => (
                    <td key={h.field} className="px-2 py-1.5 whitespace-nowrap">{formatPabsCell(h.field, r[h.field])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-border bg-muted/20 shrink-0">
          <div className="flex items-center gap-6 text-[11px]">
            <span className="text-muted-foreground"><strong className="text-foreground">{rows.length}</strong> records</span>
            <span className="text-muted-foreground">Total Area: <strong className="text-[#166534]">{totalArea.toFixed(2)} ha</strong></span>
            <span className="text-muted-foreground">Total AC: <strong className="text-[#ca8a04]">₱{totalAC.toLocaleString()}</strong></span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
            <button
              onClick={() => window.open(getAssessmentsExportPabsUrl(), "_blank")}
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

// ─── Areas Affected Modal ────────────────────────────────────────────────────
// Every area named in the typhoon's TCB signals, merged across all its
// bulletins -- unlike `typhoonSummary.areas_hit` (tbl_area_exposure_summary),
// this does not drop areas whose name failed to match an AdminBoundary row
// in ExposureCalculatorService (backend/app/services/exposure_calculator.py),
// so it stays the authoritative "all areas listed in the TCB" view even when
// exposure hasn't been computed for some of them.
interface MergedArea {
  area_name: string;
  island_group: number;
  max_signal_level: number;
  exposure: TyphoonSummaryArea | null;
}

// PAGASA's fixed TCWS column order (backend/app/services/bulletin_parser.py).
// Only Mindanao (2) is matched against AdminBoundary and feeds exposure/
// indemnity calculations -- Luzon/Visayas are informational only, listed
// as-named in the bulletin so a GIS specialist can see the storm's full
// national footprint.
const ISLAND_GROUP_LABELS: Record<number, string> = { 0: "Luzon", 1: "Visayas", 2: "Mindanao" };

function AreasAffectedModal({
  typhoonName, tcbIds, typhoonSummary, onClose,
}: {
  typhoonName: string;
  tcbIds: number[];
  typhoonSummary: TyphoonSummary | null;
  onClose: () => void;
}) {
  const [areas, setAreas] = useState<MergedArea[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    Promise.all(tcbIds.map(id => getBulletinSignals(id)))
      .then(signalLists => {
        const merged = new Map<string, MergedArea>();
        for (const signals of signalLists) {
          for (const s of signals as TcbSignal[]) {
            const key = `${s.island_group}:${s.area_name.trim().toLowerCase()}`;
            const existing = merged.get(key);
            if (existing) existing.max_signal_level = Math.max(existing.max_signal_level, s.signal_level);
            else merged.set(key, { area_name: s.area_name, island_group: s.island_group, max_signal_level: s.signal_level, exposure: null });
          }
        }
        // Exposure/indemnity data only ever exists for Mindanao (island_group
        // 2, this project's insured Region X area) -- match only within that
        // group so a same-named Luzon/Visayas phrase can never wrongly pick up
        // a Region X municipality's exposure numbers.
        for (const area of typhoonSummary?.areas_hit ?? []) {
          const m = merged.get(`2:${area.municipality.trim().toLowerCase()}`);
          if (m) m.exposure = area;
        }
        setAreas(Array.from(merged.values()).sort((a, b) =>
          a.island_group - b.island_group ||
          b.max_signal_level - a.max_signal_level ||
          a.area_name.localeCompare(b.area_name)
        ));
      })
      .catch(err => setError(err instanceof Error ? err.message : "Failed to load TCB signal areas."))
      .finally(() => setIsLoading(false));
  }, [tcbIds, typhoonSummary]);

  const mindanaoCount = areas.filter(a => a.island_group === 2).length;
  const matchedCount = areas.filter(a => a.exposure !== null).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[95vw] max-w-4xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#166534]/10 flex items-center justify-center">
              <MapPin size={15} className="text-[#166534]" />
            </div>
            <div>
              <p className="text-sm font-bold">Areas Affected — Typhoon {typhoonName}</p>
              <p className="text-[10px] text-muted-foreground">
                All areas listed across {tcbIds.length} TCB bulletin(s), merged by highest signal level
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        {!isLoading && !error && areas.length > 0 && (
          <div className="flex items-center gap-2 px-5 py-2 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-100 shrink-0">
            <AlertCircle size={11} className="text-blue-600 shrink-0" />
            <p className="text-[10px] text-blue-700 dark:text-blue-300">
              {matchedCount} of {mindanaoCount} Mindanao (Region X) area(s) have computed exposure data (Compute Assessments requires this). Luzon/Visayas areas are listed as-named in the bulletin for situational awareness only — they're outside the insured area and never have exposure data.
            </p>
          </div>
        )}

        <div className="overflow-auto flex-1 px-1">
          {isLoading ? (
            <p className="px-4 py-6 text-[11px] text-muted-foreground text-center">Loading TCB signal areas…</p>
          ) : error ? (
            <p className="px-4 py-6 text-[11px] text-red-600 text-center">{error}</p>
          ) : areas.length === 0 ? (
            <p className="px-4 py-6 text-[11px] text-muted-foreground text-center">No areas listed in this typhoon's TCB signals.</p>
          ) : (
            <table className="w-full text-[10px]">
              <thead className="sticky top-0 z-10">
                <tr className="bg-[#1e3a5f] text-white">
                  <th className="px-2.5 py-2 text-left font-semibold">Island Group</th>
                  <th className="px-2.5 py-2 text-left font-semibold">Area (as named in TCB)</th>
                  <th className="px-2.5 py-2 text-left font-semibold">Signal Number</th>
                  <th className="px-2.5 py-2 text-left font-semibold">Exposure (h)</th>
                  <th className="px-2.5 py-2 text-left font-semibold">Start Time</th>
                  <th className="px-2.5 py-2 text-left font-semibold">End Time</th>
                </tr>
              </thead>
              <tbody>
                {areas.map((a, i) => (
                  <tr key={`${a.island_group}:${a.area_name}`} className={`border-t border-border ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                    <td className="px-2.5 py-1.5 text-muted-foreground">{ISLAND_GROUP_LABELS[a.island_group] ?? "—"}</td>
                    <td className="px-2.5 py-1.5 font-semibold text-[#166534]">{a.area_name}</td>
                    <td className="px-2.5 py-1.5">Signal No. {a.max_signal_level}</td>
                    <td className="px-2.5 py-1.5">{a.exposure?.total_exposure_hours ?? "—"}</td>
                    <td className="px-2.5 py-1.5">{formatDateTime(a.exposure?.start_time ?? null)}</td>
                    <td className="px-2.5 py-1.5">{formatDateTime(a.exposure?.end_time ?? null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-end px-5 py-3 border-t border-border bg-muted/20 shrink-0">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Close</button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Module ─────────────────────────────────────────────────────────────
interface AssessmentModuleProps {
  darkMode: boolean;
}

export function AssessmentModule({ darkMode }: AssessmentModuleProps) {
  const [rows, setRows] = useState<PabsAssessmentRow[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [filterMuni, setFilterMuni] = useState("All");
  const [filterSignal, setFilterSignal] = useState("All");
  const [sortField, setSortField] = useState<SortField>("FARMER_NAME");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const [showCsvPreview, setShowCsvPreview] = useState(false);

  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [selectedTyphoonId, setSelectedTyphoonId] = useState<number | null>(null);
  const [typhoonSummary, setTyphoonSummary] = useState<TyphoonSummary | null>(null);
  const [isLoadingTyphoonSummary, setIsLoadingTyphoonSummary] = useState(false);
  const [typhoonSummaryError, setTyphoonSummaryError] = useState<string | null>(null);
  const [showAreasModal, setShowAreasModal] = useState(false);

  const [isComputingAssessments, setIsComputingAssessments] = useState(false);

  const handleSelectTyphoon = (typhoonId: number) => {
    setShowAreasModal(false);
    if (selectedTyphoonId === typhoonId) {
      setSelectedTyphoonId(null);
      setTyphoonSummary(null);
      setTyphoonSummaryError(null);
      return;
    }
    setSelectedTyphoonId(typhoonId);
    setTyphoonSummary(null);
    setTyphoonSummaryError(null);
    setIsLoadingTyphoonSummary(true);
    getTyphoonSummary(typhoonId)
      .then(setTyphoonSummary)
      .catch(error => setTyphoonSummaryError(error instanceof Error ? error.message : "Failed to load typhoon summary."))
      .finally(() => setIsLoadingTyphoonSummary(false));
  };

  // ParametricAssessment.calculate_final_payout() combines the typhoon's whole
  // TCB range into one result internally (via ExposureCalculatorService), so any
  // one of its bulletins works here -- the latest is used only as the "as of"
  // date for insurance-effectivity eligibility.
  const handleComputeAssessments = () => {
    if (selectedTyphoonId === null) return;
    const typhoonBulletins = bulletins.filter(b => b.typhoon_id === selectedTyphoonId);
    const latest = typhoonBulletins.reduce<Bulletin | null>(
      (a, b) => (a === null || b.bulletin_count > a.bulletin_count ? b : a), null
    );
    if (!latest) return;

    setIsComputingAssessments(true);
    calculateAssessments(selectedTyphoonId, latest.tcb_id)
      .then(res => {
        toast.success(`Computed ${res.assessments_computed} assessment(s) for this typhoon.`);
        loadSummary();
      })
      .catch(error => toast.error(error instanceof Error ? error.message : "Failed to compute assessments."))
      .finally(() => setIsComputingAssessments(false));
  };

  const loadSummary = () => {
    setIsLoading(true);
    setLoadError(null);
    getAssessmentsPabsSummary()
      .then(res => setRows(res.data))
      .catch(error => setLoadError(error instanceof Error ? error.message : "Failed to load assessment summary."))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    loadSummary();
    getBulletins().then(setBulletins).catch(() => setBulletins([]));
  }, []);

  // One row per typhoon NAME (not typhoon_id) -- a bulletin-title parsing bug
  // on the backend has created multiple typhoon_id rows sharing the same real
  // typhoon name (e.g. "KIYAPO" and "KIYAPO Issued at"); merge those here so
  // the same typhoon doesn't show up twice in the list. The first-seen
  // typhoon_id is kept as the one used to query the exposure summary --
  // inherits the same known limitation if a typhoon's bulletins got split
  // across more than one typhoon_id.
  const typhoons = useMemo(() => {
    const byName = new Map<string, { typhoon_name: string; typhoon_id: number; bulletin_count: number }>();
    for (const b of bulletins) {
      const existing = byName.get(b.typhoon_name);
      if (existing) existing.bulletin_count += 1;
      else byName.set(b.typhoon_name, { typhoon_name: b.typhoon_name, typhoon_id: b.typhoon_id, bulletin_count: 1 });
    }
    return Array.from(byName.values());
  }, [bulletins]);

  const municipalities = useMemo(() => {
    const set = new Set(rows.map(r => r.municipality).filter((m): m is string => !!m));
    return ["All", ...Array.from(set).sort()];
  }, [rows]);

  const signals = useMemo(() => {
    const set = new Set(rows.map(r => r.WIND_VELOCITY).filter((s): s is number => s != null));
    return ["All", ...Array.from(set).sort((a, b) => a - b).map(String)];
  }, [rows]);

  // Rows carry TYPHOON_NAME as a plain string (not a typhoon_id), which
  // sidesteps the bulletin-title-parsing quirk noted above `typhoons` --
  // matching by name is exactly how that list is already deduped/selected.
  const selectedTyphoonName = selectedTyphoonId === null
    ? null
    : typhoons.find(t => t.typhoon_id === selectedTyphoonId)?.typhoon_name ?? null;

  const filtered = useMemo(() => rows
    .filter(r => selectedTyphoonName === null || r.TYPHOON_NAME === selectedTyphoonName)
    .filter(r => filterMuni === "All" || r.municipality === filterMuni)
    .filter(r => filterSignal === "All" || r.WIND_VELOCITY === Number(filterSignal))
    .sort((a, b) => {
      const va = a[sortField] ?? (typeof a[sortField] === "number" ? 0 : "");
      const vb = b[sortField] ?? (typeof b[sortField] === "number" ? 0 : "");
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    }), [rows, selectedTyphoonName, filterMuni, filterSignal, sortField, sortDir]);

  const handleSort = (f: SortField) => {
    if (sortField === f) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(f); setSortDir("asc"); }
  };

  const totalArea = filtered.reduce((s, r) => s + (r.AREA ?? 0), 0);
  const totalAC = filtered.reduce((s, r) => s + (r.AC ?? 0), 0);

  const muniChartData = useMemo(() => {
    const totals = new Map<string, number>();
    for (const r of filtered) {
      const key = r.municipality ?? "Unknown";
      totals.set(key, (totals.get(key) ?? 0) + (r.AC ?? 0));
    }
    return Array.from(totals.entries()).map(([name, ac]) => ({ name, ac: ac / 1000 }));
  }, [filtered]);

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field
      ? sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
      : <ArrowUpDown size={10} className="opacity-30" />;

  const sortableCols: { l: string; f: SortField }[] = [
    { l: "Farmer", f: "FARMER_NAME" },
    { l: "Municipality", f: "municipality" },
    { l: "Typhoon", f: "TYPHOON_NAME" },
    { l: "Area", f: "AREA" },
    { l: "Exp (h)", f: "PERIOD_OF_EXPOSURE" },
    { l: "Wind", f: "WIND_VELOCITY" },
    { l: "AC", f: "AC" },
  ];

  return (
    <div className="h-full flex overflow-hidden bg-background">
      {showCsvPreview && (
        <CSVPreviewModal rows={filtered} onClose={() => setShowCsvPreview(false)} />
      )}

      {/* Left: Typhoons — click one to view its exposure summary */}
      <div className="w-56 shrink-0 flex flex-col border-r border-border bg-card overflow-hidden">
        <div className="px-3 py-2.5 border-b border-border">
          <p className="text-[11px] font-bold">Typhoons</p>
          <p className="text-[9px] text-muted-foreground mt-0.5">Click a typhoon to view its exposure summary</p>
        </div>
        <div className="flex-1 overflow-auto py-1 space-y-1 px-2">
          {typhoons.map(t => (
            <button
              key={t.typhoon_name}
              onClick={() => handleSelectTyphoon(t.typhoon_id)}
              className={`w-full text-left rounded-lg px-2.5 py-2 border transition-colors ${
                selectedTyphoonId === t.typhoon_id
                  ? "bg-[#166534]/10 border-[#166534]/40"
                  : "bg-background border-border hover:bg-muted/50"
              }`}
            >
              <p className="text-[10px] font-bold">Typhoon {t.typhoon_name}</p>
              <p className="text-[9px] text-muted-foreground">{t.bulletin_count} bulletins (TCB 1-{t.bulletin_count})</p>
            </button>
          ))}
        </div>
      </div>

      {/* Right: Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">

      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-card border-b border-border shrink-0 flex-wrap gap-y-1">
        <div className="flex items-center gap-2">
          <FileSpreadsheet size={14} className="text-[#166534]" />
          <span className="text-sm font-semibold">Assessment & Reporting</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
            {selectedTyphoonName ? `Typhoon ${selectedTyphoonName} only` : "All typhoons combined"}
          </span>
        </div>
        <div className="flex items-center gap-2 ml-auto flex-wrap gap-y-1">
          <button
            onClick={loadSummary}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border text-[11px] font-medium hover:bg-muted disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} /> Refresh
          </button>
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
            {signals.map(s => <option key={s} value={s}>{s === "All" ? "All Wind Velocities" : `${s} km/h`}</option>)}
          </select>
          <button
            onClick={() => setShowCsvPreview(true)}
            disabled={filtered.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#166534] text-white text-[11px] font-medium hover:bg-[#14532d] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Eye size={11} /> Review & Export CSV (PABS Format)
          </button>
        </div>
      </div>

      {loadError && (
        <div className="px-4 py-2 text-[11px] text-white bg-red-600 shrink-0">{loadError}</div>
      )}

      {selectedTyphoonId !== null && (
        <div className="mx-3 mt-3 flex items-center gap-2 px-3 py-2 border border-border rounded-xl shrink-0 bg-card">
          <Calculator size={11} className="text-[#166534] shrink-0" />
          <p className="text-[10px] font-semibold">
            Typhoon {typhoonSummary?.typhoon_name ?? typhoons.find(t => t.typhoon_id === selectedTyphoonId)?.typhoon_name ?? ""} selected
          </p>
          {isLoadingTyphoonSummary && <RefreshCw size={11} className="animate-spin text-muted-foreground" />}
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setShowAreasModal(true)}
              className="flex items-center gap-1 px-2 py-1 rounded border border-[#1e3a5f]/30 text-[#1e3a5f] text-[9px] font-medium hover:bg-[#1e3a5f]/10 transition-colors"
            >
              <MapPin size={10} /> View Areas Affected
            </button>
            {typhoonSummary && typhoonSummary.areas_hit.length > 0 && (
              <button
                onClick={handleComputeAssessments}
                disabled={isComputingAssessments}
                className="flex items-center gap-1 px-2 py-1 rounded border border-[#166534]/30 text-[#166534] text-[9px] font-medium hover:bg-[#166534]/10 disabled:opacity-50 transition-colors"
              >
                <Calculator size={10} />
                {isComputingAssessments ? "Computing…" : "Compute Assessments"}
              </button>
            )}
          </div>
        </div>
      )}

      {typhoonSummaryError && (
        <p className="mx-3 mt-2 px-3 py-2 text-[10px] text-red-600 border border-border rounded-xl shrink-0">{typhoonSummaryError}</p>
      )}

      {showAreasModal && selectedTyphoonId !== null && (
        <AreasAffectedModal
          typhoonName={typhoonSummary?.typhoon_name ?? typhoons.find(t => t.typhoon_id === selectedTyphoonId)?.typhoon_name ?? ""}
          tcbIds={bulletins.filter(b => b.typhoon_id === selectedTyphoonId).map(b => b.tcb_id)}
          typhoonSummary={typhoonSummary}
          onClose={() => setShowAreasModal(false)}
        />
      )}

      {isLoading && rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[11px] text-muted-foreground">Loading assessment summary…</p>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-8">
          <p className="text-sm font-semibold">No assessments computed yet</p>
          <p className="text-[11px] text-muted-foreground">Assessments will appear here once computed for any typhoon.</p>
        </div>
      ) : selectedTyphoonName && filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-8">
          <p className="text-sm font-semibold">No assessments computed yet for Typhoon {selectedTyphoonName}</p>
          <p className="text-[11px] text-muted-foreground">
            These records belong to other typhoons. Use "Compute Assessments" above once this typhoon's exposure is ready, or click it again to deselect and see all typhoons.
          </p>
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-3 gap-2.5 p-3 shrink-0">
            {[
              { label: "Total Records", value: filtered.length, unit: "", color: "#1e3a5f" },
              { label: "Total Area", value: totalArea.toFixed(1), unit: "ha", color: "#166534" },
              { label: "Total AC (Sum Insured)", value: `₱${(totalAC / 1000).toFixed(0)}K`, unit: "", color: "#ca8a04" },
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
                    {sortableCols.map(col => (
                      <th
                        key={col.f}
                        className="px-2 py-1.5 text-left font-semibold cursor-pointer hover:bg-white/10 whitespace-nowrap"
                        onClick={() => handleSort(col.f)}
                      >
                        <span className="flex items-center gap-0.5">{col.l}<SortIcon field={col.f} /></span>
                      </th>
                    ))}
                    <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Farmer ID</th>
                    <th className="px-2 py-1.5 text-left font-semibold whitespace-nowrap">Farm ID</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={r.assessment_id} className={`border-t border-border hover:bg-muted/40 transition-colors ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                      <td className="px-2 py-1.5 font-medium whitespace-nowrap">{formatCell(r.FARMER_NAME)}</td>
                      <td className="px-2 py-1.5 text-muted-foreground">{formatCell(r.municipality)}</td>
                      <td className="px-2 py-1.5">{formatCell(r.TYPHOON_NAME)}</td>
                      <td className="px-2 py-1.5 text-right">{r.AREA != null ? r.AREA.toFixed(2) : "—"}</td>
                      <td className="px-2 py-1.5 text-right">{formatCell(r.PERIOD_OF_EXPOSURE)}</td>
                      <td className="px-2 py-1.5 text-right">{r.WIND_VELOCITY != null ? `${r.WIND_VELOCITY} km/h` : "—"}</td>
                      <td className="px-2 py-1.5 text-right font-bold text-[#166534]">{r.AC != null ? `₱${r.AC.toLocaleString()}` : "—"}</td>
                      <td className="px-2 py-1.5 font-mono text-muted-foreground">{formatCell(r.FARMERID)}</td>
                      <td className="px-2 py-1.5 font-mono text-[#166534]">#{formatCell(r.FARMID)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-[#166534]/10 border-t-2 border-[#166534] font-bold text-[11px]">
                    <td colSpan={3} className="px-2 py-2">TOTAL ({filtered.length} records)</td>
                    <td className="px-2 py-2 text-right">{totalArea.toFixed(2)}</td>
                    <td colSpan={2} />
                    <td className="px-2 py-2 text-right text-[#166534]">₱{totalAC.toLocaleString()}</td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>

            {/* Right: Chart */}
            <div className="w-52 shrink-0 flex flex-col border-l border-border overflow-hidden">
              <div className="px-3 py-2 border-b border-border bg-card shrink-0">
                <p className="text-[11px] font-semibold">AC by Municipality</p>
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
                    <Bar dataKey="ac" name="AC (₱K)" fill="#ca8a04" radius={[0, 4, 4, 0]} />
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
