import { useState, useMemo, useEffect } from "react";
import { toast } from "sonner";
import {
  Download, Eye, ChevronDown, ChevronUp, ArrowUpDown,
  FileSpreadsheet, RefreshCw, AlertCircle, Calculator, MapPin, Lock,
} from "lucide-react";
import {
  getAssessmentsPabsSummary, downloadAssessmentsPabsCsv, getBulletins, getTyphoonSummary, calculateAssessments,
  getTyphoonExposure, getFieldVerifyList, downloadFieldVerifyCsv, getArchivedTyphoons, getArchivedTyphoonRows,
  PabsAssessmentRow, Bulletin, TyphoonSummary, TyphoonExposure, FieldVerifyList, FieldVerifyRow,
  AssessmentJob, getAssessmentJob, getActiveAssessmentJob,
  ArchivedTyphoon, ArchivedTyphoonRows,
} from "@/lib/api";
import { ExposureTable } from "./ExposureTable";
import { AssessmentProgressBar } from "./AssessmentProgressBar";
import { formatPeso, sumPesos } from "@/lib/format";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// How often a running assessment calculation's progress is polled.
const ASSESSMENT_POLL_MS = 500;

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
  const totalAC = sumPesos(rows.map(r => r.AC));

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
            <span className="text-muted-foreground">Total AC: <strong className="text-[#ca8a04]">{formatPeso(totalAC)}</strong></span>
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

// ─── SAR Field Verification Modal ────────────────────────────────────────────
// The typhoon's YELLOW "field_verify" farms from its stored SAR planted check
// (2026-10-13, per Cristian). Read-only: downloading locks nothing, unlike the
// PABS export above.
const FIELD_VERIFY_HEADERS: { label: string; field: keyof FieldVerifyRow }[] = [
  { label: "FARMER NAME", field: "FARMER_NAME" },
  { label: "FARMERSID", field: "FARMERID" },
  { label: "FARMID", field: "FARMID" },
  { label: "CIC NO", field: "CIC_NO" },
  { label: "PROVINCE", field: "PROVINCE" },
  { label: "MUNICIPALITY", field: "MUNICIPALITY" },
  { label: "BARANGAY", field: "BARANGAY" },
  { label: "AREA", field: "AREA" },
  { label: "TYPHOON_NAME", field: "TYPHOON_NAME" },
  { label: "SAR REASON", field: "SAR_REASON" },
];

// Left-aligned like FARMER NAME in the PABS preview; the rest are centered.
const FIELD_VERIFY_LEFT = new Set<string>(["FARMER_NAME", "SAR_REASON"]);

function FieldVerifyModal({ list, onClose }: { list: FieldVerifyList; onClose: () => void }) {
  const [isDownloading, setIsDownloading] = useState(false);
  const totalArea = list.rows.reduce((s, r) => s + (r.AREA ?? 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[95vw] max-w-7xl max-h-[88vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#ca8a04]/10 flex items-center justify-center">
              <AlertCircle size={15} className="text-[#ca8a04]" />
            </div>
            <div>
              <p className="text-sm font-bold">SAR Field Verification List — Typhoon {list.typhoon_name}</p>
              <p className="text-[10px] text-muted-foreground">
                Eligible farms the automatic planted check marked yellow · SAR checked {formatDateTime(list.checked_at)}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        <div className="flex items-center gap-2 px-5 py-2 bg-[#ca8a04]/10 border-b border-border shrink-0">
          <AlertCircle size={11} className="text-[#ca8a04] shrink-0" />
          <p className="text-[10px] text-[#8a5d00] dark:text-yellow-300">
            Read-only export. Downloading does not lock any policy and does not change the PABS export.
          </p>
        </div>

        <div className="overflow-auto flex-1 px-1">
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 z-10">
              <tr className="bg-[#ca8a04] text-white">
                {FIELD_VERIFY_HEADERS.map(h => (
                  <th key={h.field} className={`px-2 py-1.5 font-semibold whitespace-nowrap ${FIELD_VERIFY_LEFT.has(h.field) ? "text-left" : "text-center"}`}>{h.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.rows.map((r, i) => (
                <tr key={r.farm_id} className={`border-t border-border hover:bg-muted/30 ${i % 2 === 0 ? "bg-card" : "bg-muted/10"}`}>
                  {FIELD_VERIFY_HEADERS.map(h => (
                    <td key={h.field} className={`px-2 py-1.5 whitespace-nowrap ${FIELD_VERIFY_LEFT.has(h.field) ? "text-left" : "text-center"} ${h.field === "AREA" ? "tabular-nums" : ""}`}>
                      {h.field === "AREA"
                        ? (r.AREA != null ? r.AREA.toFixed(2) : "—")
                        : formatCell(r[h.field])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-border bg-muted/20 shrink-0">
          <div className="flex items-center gap-6 text-[11px]">
            <span className="text-muted-foreground"><strong className="text-foreground">{list.rows.length}</strong> farms to verify</span>
            <span className="text-muted-foreground">of <strong className="text-foreground">{list.assessed}</strong> eligible farms</span>
            <span className="text-muted-foreground">Total Area: <strong className="text-[#166534]">{totalArea.toFixed(2)} ha</strong></span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
            <button
              onClick={() => {
                setIsDownloading(true);
                downloadFieldVerifyCsv(list.typhoon_id)
                  .then(() => toast.success(`Field verification list exported (${list.rows.length} farms).`))
                  .catch(e => toast.error(e.message))
                  .finally(() => setIsDownloading(false));
              }}
              disabled={isDownloading}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#ca8a04] text-white text-xs font-semibold hover:bg-[#a16207] disabled:opacity-50 transition-colors"
            >
              <Download size={12} /> {isDownloading ? "Downloading…" : "Download CSV"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Areas Affected Modal ────────────────────────────────────────────────────
// Every municipality under a wind signal during the typhoon, with its Max
// Signal, hours under each of Signal 1-5 and Total Exposure -- the same
// backend rows the Main Dashboard's Exposure Summary shows (2026-10-22; the
// per-TCB signal merge that used to run here is now done once, server-side,
// by ExposureCalculatorService whenever a bulletin is saved).
function AreasAffectedModal({
  typhoonId, typhoonName, onClose,
}: {
  typhoonId: number;
  typhoonName: string;
  onClose: () => void;
}) {
  const [exposure, setExposure] = useState<TyphoonExposure | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    getTyphoonExposure(typhoonId)
      .then(setExposure)
      .catch(err => setError(err instanceof Error ? err.message : "Failed to load areas affected."))
      .finally(() => setIsLoading(false));
  }, [typhoonId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[95vw] max-w-6xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#166534]/10 flex items-center justify-center">
              <MapPin size={15} className="text-[#166534]" />
            </div>
            <div>
              <p className="text-sm font-bold">Areas Affected — Typhoon {typhoonName}</p>
              <p className="text-[10px] text-muted-foreground">
                Hours each municipality spent under each wind signal{exposure ? `, across ${exposure.bulletin_count} TCB bulletin(s)` : ""}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded flex items-center justify-center hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">✕</button>
        </div>

        <div className="overflow-auto flex-1 px-4 py-3">
          {isLoading ? (
            <p className="px-4 py-6 text-[11px] text-muted-foreground text-center">Loading areas affected…</p>
          ) : error ? (
            <p className="px-4 py-6 text-[11px] text-red-600 text-center">{error}</p>
          ) : exposure ? (
            <ExposureTable exposure={exposure} showIslandGroup headerColor="#1e3a5f" />
          ) : null}
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

  // The selected typhoon's assessment calculation run (2026-10-22): real
  // backend progress, polled while it runs. null = none started/resumed.
  const [assessmentJob, setAssessmentJob] = useState<AssessmentJob | null>(null);
  const isComputingAssessments = assessmentJob?.status === "processing";

  // A calculation still running for this typhoon (e.g. after a page refresh,
  // or the automatic final-bulletin run) is picked back up.
  useEffect(() => {
    setAssessmentJob(null);
    if (selectedTyphoonId === null) return;
    let cancelled = false;
    getActiveAssessmentJob(selectedTyphoonId)
      .then(res => { if (!cancelled && res.job?.status === "processing") setAssessmentJob(res.job); })
      .catch(() => { /* no job info -- the Compute button still works */ });
    return () => { cancelled = true; };
  }, [selectedTyphoonId]);

  // One poll loop per job id: each request waits for the previous one, so
  // updates can never arrive out of order or from two loops at once.
  const pollingJobId = assessmentJob?.status === "processing" ? assessmentJob.job_id : null;
  useEffect(() => {
    if (pollingJobId === null) return;
    let cancelled = false;
    (async () => {
      while (!cancelled) {
        await new Promise(resolve => setTimeout(resolve, ASSESSMENT_POLL_MS));
        if (cancelled) return;
        let job: AssessmentJob;
        try {
          job = await getAssessmentJob(pollingJobId);
        } catch (error) {
          if (cancelled) return;
          toast.error(error instanceof Error ? error.message : "Lost track of the assessment calculation.");
          setAssessmentJob(null);
          return;
        }
        if (cancelled) return;
        setAssessmentJob(job);
        if (job.status === "done") {
          toast.success(`Computed ${job.result?.assessments_computed ?? 0} assessment(s) for this typhoon.`);
          loadSummary();
          return;
        }
        if (job.status === "error") {
          toast.error(job.error ?? "Assessment calculation failed.");
          return;
        }
      }
    })();
    return () => { cancelled = true; };
    // loadSummary is a plain function redefined each render; the loop only
    // needs it once, at completion.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollingJobId]);

  // SAR field verification list for the selected typhoon (2026-10-13). null
  // while loading, on error, or with no typhoon selected.
  const [fieldVerify, setFieldVerify] = useState<FieldVerifyList | null>(null);
  const [showFieldVerifyModal, setShowFieldVerifyModal] = useState(false);

  // Archived typhoons (2026-10-22): after Archive & Clear a typhoon's rows
  // leave the live DB, so selecting it shows them from the archive instead,
  // read-only. Keyed by name, same as the deduped typhoon list below.
  const [archivedByName, setArchivedByName] = useState<Map<string, ArchivedTyphoon>>(new Map());
  const [archivedView, setArchivedView] = useState<ArchivedTyphoonRows | null>(null);
  const [isLoadingArchived, setIsLoadingArchived] = useState(false);
  const [archivedError, setArchivedError] = useState<string | null>(null);

  useEffect(() => {
    setFieldVerify(null);
    setShowFieldVerifyModal(false);
    if (selectedTyphoonId === null) return;
    // Ignore a late response for a typhoon that's no longer selected.
    let cancelled = false;
    getFieldVerifyList(selectedTyphoonId)
      .then(res => { if (!cancelled) setFieldVerify(res.data); })
      .catch(() => { /* button stays disabled */ });
    return () => { cancelled = true; };
  }, [selectedTyphoonId]);

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

    const typhoonId = selectedTyphoonId;
    calculateAssessments(typhoonId, latest.tcb_id)
      .then(res => {
        if (res.already_running) toast.info("An assessment calculation for this typhoon is already running.");
        return getAssessmentJob(res.job_id);
      })
      .then(job => setAssessmentJob(job))
      .catch(error => toast.error(error instanceof Error ? error.message : "Failed to compute assessments."));
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
    getArchivedTyphoons()
      .then(res => setArchivedByName(new Map(res.data.map(t => [t.name, t]))))
      .catch(() => setArchivedByName(new Map()));
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

  // Rows carry TYPHOON_NAME as a plain string (not a typhoon_id), which
  // sidesteps the bulletin-title-parsing quirk noted above `typhoons` --
  // matching by name is exactly how that list is already deduped/selected.
  const selectedTyphoonName = selectedTyphoonId === null
    ? null
    : typhoons.find(t => t.typhoon_id === selectedTyphoonId)?.typhoon_name ?? null;

  // An archived typhoon with no live rows left is shown from the archive.
  // Live rows win if it was assessed again after a clear (they're current;
  // the archive stays viewable from Database Backup).
  const selectedArchive = selectedTyphoonName ? archivedByName.get(selectedTyphoonName) ?? null : null;
  const hasLiveRowsForSelected = selectedTyphoonName !== null && rows.some(r => r.TYPHOON_NAME === selectedTyphoonName);
  const showArchived = selectedArchive !== null && !hasLiveRowsForSelected && !isLoading;

  useEffect(() => {
    setArchivedView(null);
    setArchivedError(null);
    if (!showArchived || selectedArchive === null) return;
    let cancelled = false;
    setIsLoadingArchived(true);
    getArchivedTyphoonRows(selectedArchive.typhoon_id)
      .then(res => { if (!cancelled) setArchivedView(res.data); })
      .catch(error => { if (!cancelled) setArchivedError(error instanceof Error ? error.message : "Failed to load archived records."); })
      .finally(() => { if (!cancelled) setIsLoadingArchived(false); });
    return () => { cancelled = true; };
  }, [showArchived, selectedArchive]);

  const isArchivedView = showArchived && archivedView !== null;
  const displayRows = isArchivedView ? archivedView.rows : rows;

  const municipalities = useMemo(() => {
    const set = new Set(displayRows.map(r => r.municipality).filter((m): m is string => !!m));
    return ["All", ...Array.from(set).sort()];
  }, [displayRows]);

  const signals = useMemo(() => {
    const set = new Set(displayRows.map(r => r.wind_signal).filter((s): s is number => s != null));
    return ["All", ...Array.from(set).sort((a, b) => a - b).map(String)];
  }, [displayRows]);

  const filtered = useMemo(() => displayRows
    .filter(r => selectedTyphoonName === null || r.TYPHOON_NAME === selectedTyphoonName)
    .filter(r => filterMuni === "All" || r.municipality === filterMuni)
    .filter(r => filterSignal === "All" || r.wind_signal === Number(filterSignal))
    .sort((a, b) => {
      const va = a[sortField] ?? (typeof a[sortField] === "number" ? 0 : "");
      const vb = b[sortField] ?? (typeof b[sortField] === "number" ? 0 : "");
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    }), [displayRows, selectedTyphoonName, filterMuni, filterSignal, sortField, sortDir]);

  const handleSort = (f: SortField) => {
    if (sortField === f) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(f); setSortDir("asc"); }
  };

  const totalArea = filtered.reduce((s, r) => s + (r.AREA ?? 0), 0);
  const totalAC = sumPesos(filtered.map(r => r.AC));

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
              <p className="text-[13px] font-bold flex items-center gap-1.5">
                Typhoon {t.typhoon_name}
                {archivedByName.has(t.typhoon_name) && (
                  <span className="flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded-full border border-border text-muted-foreground">
                    <Lock size={8} /> Archived
                  </span>
                )}
              </p>
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
          {/* Disabled for an archived typhoon: the PABS export locks the
              exported policies as used, and archived rows are read-only. */}
          <button
            onClick={() => setShowCsvPreview(true)}
            disabled={filtered.length === 0 || showArchived}
            title={showArchived ? "Archived typhoons are read-only" : undefined}
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
            {/* Archived typhoon: only View Areas Affected stays -- its farms
                are no longer live, so SAR export and Compute don't apply. */}
            {!showArchived && <>
            {fieldVerify && fieldVerify.checked === 0 && (
              <span className="text-[9px] text-muted-foreground">Run the SAR planted check in Spatial Analysis first</span>
            )}
            {fieldVerify && fieldVerify.checked > 0 && fieldVerify.assessed === 0 && (
              <span className="text-[9px] text-muted-foreground">Compute Assessments first</span>
            )}
            {fieldVerify && fieldVerify.checked > 0 && fieldVerify.assessed > 0 && fieldVerify.rows.length === 0 && (
              <span className="text-[9px] text-muted-foreground">No farms need field verification</span>
            )}
            <button
              onClick={() => setShowFieldVerifyModal(true)}
              disabled={!fieldVerify || fieldVerify.rows.length === 0}
              className="flex items-center gap-1 px-2 py-1 rounded border border-[#ca8a04]/50 bg-[#ca8a04]/10 text-[#8a5d00] dark:text-yellow-300 text-[9px] font-medium hover:bg-[#ca8a04]/20 disabled:opacity-45 disabled:cursor-not-allowed transition-colors"
            >
              <Download size={10} /> Export SAR Field Verification List
              {fieldVerify && fieldVerify.checked > 0 && fieldVerify.assessed > 0 && (
                <span className="px-1.5 rounded-full bg-[#ca8a04] text-white font-bold tabular-nums">{fieldVerify.rows.length}</span>
              )}
            </button>
            </>}
            <button
              onClick={() => setShowAreasModal(true)}
              className="flex items-center gap-1 px-2 py-1 rounded border border-[#1e3a5f]/30 text-[#1e3a5f] text-[9px] font-medium hover:bg-[#1e3a5f]/10 transition-colors"
            >
              <MapPin size={10} /> View Areas Affected
            </button>
            {!showArchived && typhoonSummary && typhoonSummary.areas_hit.length > 0 && (
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

      {!showArchived && assessmentJob && (
        <div className="mx-3 mt-2 px-3 py-2 rounded-xl shrink-0 border border-border bg-card">
          <AssessmentProgressBar job={assessmentJob} />
        </div>
      )}

      {showArchived && selectedArchive && (
        <div className="mx-3 mt-2 flex items-center gap-2 px-3 py-2 rounded-xl shrink-0 border border-amber-300 bg-amber-50 dark:bg-amber-950/30 text-[10px] text-amber-800 dark:text-amber-300">
          <Lock size={11} className="shrink-0" />
          <span>
            <strong>Read-only</strong> — from archive #{selectedArchive.archive_id} ({selectedArchive.label}),
            archived {formatDateTime(selectedArchive.archived_at)}. These records were cleared from the live system.
          </span>
        </div>
      )}
      {archivedError && (
        <p className="mx-3 mt-2 px-3 py-2 text-[10px] text-red-600 border border-border rounded-xl shrink-0">{archivedError}</p>
      )}

      {typhoonSummaryError && (
        <p className="mx-3 mt-2 px-3 py-2 text-[10px] text-red-600 border border-border rounded-xl shrink-0">{typhoonSummaryError}</p>
      )}

      {showFieldVerifyModal && fieldVerify && (
        <FieldVerifyModal list={fieldVerify} onClose={() => setShowFieldVerifyModal(false)} />
      )}

      {showAreasModal && selectedTyphoonId !== null && (
        <AreasAffectedModal
          typhoonId={selectedTyphoonId}
          typhoonName={typhoonSummary?.typhoon_name ?? typhoons.find(t => t.typhoon_id === selectedTyphoonId)?.typhoon_name ?? ""}
          onClose={() => setShowAreasModal(false)}
        />
      )}

      {(isLoading && rows.length === 0) || (showArchived && isLoadingArchived) ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-[11px] text-muted-foreground">
            {showArchived ? "Loading archived records…" : "Loading assessment summary…"}
          </p>
        </div>
      ) : displayRows.length === 0 ? (
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
              { label: "Total AC (Sum Insured)", value: formatPeso(totalAC), unit: "", color: "#ca8a04" },
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
                      <td className="px-2 py-1.5 text-center font-bold text-[#166534] dark:text-emerald-400">{formatPeso(r.AC)}</td>
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
                    <td className="px-2 py-2 text-center text-[#166534]">{formatPeso(totalAC)}</td>
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
