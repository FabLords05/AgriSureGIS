import { useState, useMemo, useEffect } from "react";
import { toast } from "sonner";
import {
  Download, Eye, ChevronDown, ChevronUp, ArrowUpDown,
  FileSpreadsheet, RefreshCw, AlertCircle, Calculator, MapPin,
} from "lucide-react";
import {
  getAssessmentsPabsSummary, downloadAssessmentsPabsCsv, getBulletins, getTyphoonSummary, calculateAssessments,
  getBulletinSignals,
  PabsAssessmentRow, Bulletin, TyphoonSummary, TyphoonSummaryArea, TcbSignal,
} from "@/lib/api";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// TYPHOON_NAME isn't sortable (2026-10-13, per Cristian -- unnecessary).
type SortField = "FARMER_NAME" | "province" | "municipality" | "barangay" | "AREA" | "PERIOD_OF_EXPOSURE" | "wind_signal" | "crop_stage" | "AC";
type SortDir = "asc" | "desc";

// `right` = numeric column (tabular-nums). Every column is centered except
// FARMER NAME, which is left-aligned (2026-10-12, per Fabio). Order is
// PCIC's final PABS layout (2026-10-12, per Fabio); IRID is a blank column.
// Labels are the exact CSV headers (backend PABS_CSV_HEADERS).
const PABS_HEADERS: { label: string; field: keyof PabsAssessmentRow; right?: boolean }[] = [
  { label: "FARMER NAME", field: "FARMER_NAME" },
  { label: "FARMERSID", field: "FARMERID" },
  { label: "FARMID", field: "FARMID" },
  { label: "IRID", field: "IRID" },
  { label: "CIC NO", field: "CIC_NO" },
  { label: "AREA", field: "AREA", right: true },
  { label: "TYPHOON_NAME", field: "TYPHOON_NAME" },
  { label: "PERIOD_OF_EXPOSURE", field: "PERIOD_OF_EXPOSURE", right: true },
  { label: "WIND_VELOCITY", field: "WIND_VELOCITY", right: true },
  { label: "AC", field: "AC", right: true },
  { label: "FINAL_INDEMNITY_PAYMENT", field: "FINAL_INDEMNITY_PAYMENT", right: true },
  { label: "P", field: "P", right: true },
  { label: "S", field: "S", right: true },
  { label: "REMARKS", field: "REMARKS" },
];

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

// Matches the CSV export's float_format="%.2f" -- what the preview shows for
// AREA/AC/FINAL_INDEMNITY_PAYMENT must be exactly what ends up in the downloaded file.
function formatPabsCell(field: keyof PabsAssessmentRow, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if ((field === "AREA" || field === "AC" || field === "FINAL_INDEMNITY_PAYMENT") && typeof value === "number") {
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

        <div className="overflow-auto flex-1 px-1">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#166534] text-white">
                {PABS_HEADERS.map(h => (
                  <th key={h.field} className={`px-2 py-1.5 font-semibold whitespace-nowrap ${h.field === "FARMER_NAME" ? "text-left" : "text-center"}`}>{h.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.assessment_id} className={`border-t border-border hover:bg-muted/30 ${i % 2 === 0 ? "bg-card" : "bg-muted/10"}`}>
                  {PABS_HEADERS.map(h => (
                    <td key={h.field} className={`px-2 py-1.5 whitespace-nowrap ${h.field === "FARMER_NAME" ? "text-left" : "text-center"} ${h.right ? "tabular-nums" : ""}`}>{formatPabsCell(h.field, r[h.field])}</td>
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
              onClick={() => {
                // Exporting locks every policy with a payout as used -- it
                // can't be assessed again for any later typhoon.
                if (!window.confirm("Exporting the final CSV marks every policy with a payout as used. Those policies can't be used again for a new typhoon. Continue?")) return;
                downloadAssessmentsPabsCsv()
                  .then(() => toast.success("CSV exported. Policies with a payout are now marked as used."))
                  .catch(e => toast.error(e.message));
              }}
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
// which only has rows after "Compute Assessments" has run, this shows a
// matched area (bulletin_parser.py already validates each signal against
// AdminBoundary at scrape time, nationwide as of 2026-08-20) as soon as it's
// in a bulletin, so it stays the authoritative "all areas listed in the TCB"
// view even when exposure hasn't been computed for some of them yet.
interface MergedArea {
  area_name: string;
  province: string | null;
  island_group: number;
  max_signal_level: number;
  exposure: TyphoonSummaryArea | null;
}

// PAGASA's fixed TCWS column order (backend/app/services/bulletin_parser.py).
// As of the nationwide PSGC expansion (2026-08-20), every island group is
// matched against AdminBoundary and feeds exposure/indemnity calculations --
// previously this was Mindanao (2) only.
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
            // Keyed on province+municipality, not municipality alone -- a
            // same-named municipality can exist in more than one province
            // nationwide (e.g. multiple "Santa Cruz"), so province is needed
            // to avoid merging two distinct areas into one row.
            const key = `${(s.province ?? "").trim().toLowerCase()}:${s.area_name.trim().toLowerCase()}`;
            const existing = merged.get(key);
            if (existing) existing.max_signal_level = Math.max(existing.max_signal_level, s.signal_level);
            else merged.set(key, { area_name: s.area_name, province: s.province, island_group: s.island_group, max_signal_level: s.signal_level, exposure: null });
          }
        }
        // Match on the same province+municipality key so exposure numbers
        // never get attributed to the wrong same-named area in a different
        // province -- see backend/app/services/exposure_calculator.py.
        for (const area of typhoonSummary?.areas_hit ?? []) {
          const key = `${area.province.trim().toLowerCase()}:${area.municipality.trim().toLowerCase()}`;
          const m = merged.get(key);
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
              {matchedCount} of {areas.length} area(s) have computed exposure data (Compute Assessments requires this). An area only appears here if the bulletin named a specific municipality that matched a known administrative boundary.
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
                  <tr key={`${a.province}:${a.area_name}`} className={`border-t border-border ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
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

// darkMode is still accepted (App.tsx passes it) but no longer read -- the
// AC by Municipality chart was its only use.
export function AssessmentModule(_props: AssessmentModuleProps) {
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
    const set = new Set(rows.map(r => r.wind_signal).filter((s): s is number => s != null));
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
    .filter(r => filterSignal === "All" || r.wind_signal === Number(filterSignal))
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

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field
      ? sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
      : <ArrowUpDown size={10} className="opacity-30" />;

  // Every column is centered except Farmer, left-aligned (2026-10-12, per Fabio).
  // `f: null` = header without sorting (Typhoon, 2026-10-13).
  const sortableCols: { l: string; f: SortField | null }[] = [
    { l: "Farmer", f: "FARMER_NAME" },
    { l: "Province", f: "province" },
    { l: "Municipality", f: "municipality" },
    { l: "Barangay", f: "barangay" },
    { l: "Typhoon", f: null },
    { l: "Area", f: "AREA" },
    { l: "Exp (h)", f: "PERIOD_OF_EXPOSURE" },
    { l: "Wind", f: "wind_signal" },
    { l: "Crop Stage", f: "crop_stage" },
    { l: "AC", f: "AC" },
  ];

  return (
    <div className="h-full flex overflow-hidden bg-background">
      {showCsvPreview && (
        <CSVPreviewModal rows={filtered} onClose={() => setShowCsvPreview(false)} />
      )}

      {/* Left: Typhoons — click one to view its exposure summary */}
      <div className="w-60 shrink-0 flex flex-col border-r border-border bg-card overflow-hidden">
        {/* min-h-16 matches the Top bar beside it so both bottom borders line
            up. leading-tight + py-1.5 keep the two-line hint (about 59px total)
            inside that 64px. */}
        <div className="min-h-16 shrink-0 flex flex-col justify-center px-3 py-1.5 border-b border-border">
          <p className="text-[14px] font-bold leading-tight">Typhoons</p>
          <p className="text-[11px] text-foreground/70 mt-0.5 leading-tight">Click a typhoon to view its exposure summary</p>
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
              <p className="text-[13px] font-bold">Typhoon {t.typhoon_name}</p>
              <p className="text-[12px] text-foreground/70">{t.bulletin_count} bulletins (TCB 1-{t.bulletin_count})</p>
            </button>
          ))}
        </div>
      </div>

      {/* Right: Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">

      {/* Top bar */}
      <div className="min-h-16 flex items-center gap-3 px-4 py-2 bg-card border-b border-border shrink-0 flex-wrap gap-y-1">
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
            {signals.map(s => <option key={s} value={s}>{s === "All" ? "All Wind Velocities" : `Signal ${s}`}</option>)}
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

          {/* Table */}
          <div className="flex flex-1 overflow-hidden">
            <div className="flex-1 overflow-auto">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 z-10">
                  <tr className="bg-[#1e3a5f] text-white">
                    {sortableCols.map(({ l, f }) => f === null ? (
                      <th key={l} className="px-2 py-1.5 text-center font-semibold whitespace-nowrap">{l}</th>
                    ) : (
                      <th
                        key={f}
                        className={`px-2 py-1.5 font-semibold cursor-pointer hover:bg-white/10 whitespace-nowrap ${f === "FARMER_NAME" ? "text-left" : "text-center"}`}
                        onClick={() => handleSort(f)}
                      >
                        <span className={`flex items-center gap-0.5 ${f === "FARMER_NAME" ? "" : "justify-center"}`}>{l}<SortIcon field={f} /></span>
                      </th>
                    ))}
                    <th className="px-2 py-1.5 text-center font-semibold whitespace-nowrap">Farmer ID</th>
                    <th className="px-2 py-1.5 text-center font-semibold whitespace-nowrap">Farm ID</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={r.assessment_id} className={`border-t border-border hover:bg-muted/40 transition-colors ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                      <td className="px-2 py-1.5 text-left font-medium whitespace-nowrap">{formatCell(r.FARMER_NAME)}</td>
                      <td className="px-2 py-1.5 text-center text-muted-foreground">{formatCell(r.province)}</td>
                      <td className="px-2 py-1.5 text-center text-muted-foreground">{formatCell(r.municipality)}</td>
                      <td className="px-2 py-1.5 text-center text-muted-foreground">{formatCell(r.barangay)}</td>
                      <td className="px-2 py-1.5 text-center">{formatCell(r.TYPHOON_NAME)}</td>
                      <td className="px-2 py-1.5 text-center">{r.AREA != null ? r.AREA.toFixed(2) : "—"}</td>
                      <td className="px-2 py-1.5 text-center">{formatCell(r.PERIOD_OF_EXPOSURE)}</td>
                      {/* wind_signal is the TCWS signal number; WIND_VELOCITY is km/h (CSV only). */}
                      <td className="px-2 py-1.5 text-center whitespace-nowrap">{r.wind_signal != null ? `Signal ${r.wind_signal}` : "—"}</td>
                      <td className="px-2 py-1.5 text-center whitespace-nowrap">{formatCell(r.crop_stage)}</td>
                      <td className="px-2 py-1.5 text-center font-bold text-[#166534] dark:text-emerald-400">{r.AC != null ? `₱${r.AC.toLocaleString()}` : "—"}</td>
                      <td className="px-2 py-1.5 text-center font-mono text-muted-foreground">{formatCell(r.FARMERID)}</td>
                      {/* PCIC's own FARMID, same value as the CSV (2026-10-12). */}
                      <td className="px-2 py-1.5 text-center font-mono text-[#166534] dark:text-emerald-400">{formatCell(r.FARMID)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-[#166534]/10 border-t-2 border-[#166534] font-bold text-[11px]">
                    <td colSpan={5} className="px-2 py-2 text-center">TOTAL ({filtered.length} records)</td>
                    <td className="px-2 py-2 text-center">{totalArea.toFixed(2)}</td>
                    <td colSpan={3} />
                    <td className="px-2 py-2 text-center text-[#166534]">₱{totalAC.toLocaleString()}</td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
            {/* AC by Municipality chart removed 2026-10-11 per Cristian --
                the table takes the full width now. */}
          </div>
        </>
      )}
      </div>
    </div>
  );
}
