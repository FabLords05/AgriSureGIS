import { useState, useEffect, useCallback, useMemo } from "react";
import { toast } from "sonner";
import {
  Activity, Download, FileDown,
  RefreshCw, Eye, BarChart2, TrendingUp, Zap,
  X, MapPinned, ShieldCheck,
  ChevronUp, ChevronDown, ArrowUpDown
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, CartesianGrid, Legend
} from "recharts";
import {
  Bulletin, TcbSignal, Farm, Assessment, InsuranceSummary, ActiveTyphoon,
  getBulletins, parseBulletins, getBulletinSignals,
  computeExposure, ComputeExposureResult, getAssessments, getInsuranceSummary,
  getActiveTyphoons,
} from "@/lib/api";
import { FarmsData } from "@/lib/useFarmsData";

interface FarmRow extends Farm {
  assessment: Assessment | null;
}

type BulletinSortField = "bulletin_count" | "typhoon_name" | "issued_at" | "category" | "max_sustained_winds" | "gustiness";
type SortDir = "asc" | "desc";

const GROWTH_STAGE_COLORS = ["#22c55e", "#eab308", "#f59e0b", "#86efac", "#a3a3a3"];
const SIGNAL_BAR_COLOR = "#166534";

function uniqueAreas(signals: TcbSignal[]): string[] {
  return Array.from(new Set(signals.map(s => s.area_name)));
}

function maxSignalLevel(signals: TcbSignal[]): number {
  return signals.length ? Math.max(...signals.map(s => s.signal_level)) : 0;
}

// Groups signals by level (highest first) so each level's areas can be shown
// under its own header, instead of merging every level's areas into one flat
// list under a single "highest signal" banner.
function groupAreasBySignalLevel(signals: TcbSignal[]): { level: number; areas: string[] }[] {
  const byLevel = new Map<number, Set<string>>();
  for (const s of signals) {
    if (!byLevel.has(s.signal_level)) byLevel.set(s.signal_level, new Set());
    byLevel.get(s.signal_level)!.add(s.area_name);
  }
  return Array.from(byLevel.entries())
    .sort((a, b) => b[0] - a[0])
    .map(([level, areas]) => ({ level, areas: Array.from(areas) }));
}

function signalLevelColor(level: number): string {
  return level >= 3 ? "#ef4444" : level === 2 ? "#d97706" : "#166534";
}

function formatIssuedAt(isoString: string | null | undefined): string {
  if (!isoString) return "Unknown";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

// ─── TCB Detail Viewer Modal ─────────────────────────────────────────────────
function TCBViewerModal({ bulletin, signals, isLoadingSignals, onClose }: { bulletin: Bulletin; signals: TcbSignal[]; isLoadingSignals: boolean; onClose: () => void }) {
  const highestSignal = maxSignalLevel(signals);
  const signalColor = signalLevelColor(highestSignal);
  const areasByLevel = groupAreasBySignalLevel(signals);

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
      `ISSUED: ${formatIssuedAt(bulletin.issued_at)}`,
      `MAX SUSTAINED WINDS: ${bulletin.max_sustained_winds ?? "—"} km/h`,
      `GUSTINESS: ${bulletin.gustiness ?? "—"} km/h`,
      "",
      "AREAS UNDER SIGNAL WARNING:",
      ...(areasByLevel.length
        ? areasByLevel.flatMap(({ level, areas }) => [
            `  Signal No. ${level}:`,
            ...areas.map(a => `    • ${a}`),
          ])
        : ["  (no signal data recorded for this bulletin)"]),
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
              <p className="text-[10px] text-white/60">{formatIssuedAt(bulletin.issued_at)}</p>
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
                ["Issued", formatIssuedAt(bulletin.issued_at)],
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
              ) : areasByLevel.length ? (
                <div className="space-y-2.5">
                  {areasByLevel.map(({ level, areas: levelAreas }) => (
                    <div key={level}>
                      <p className="text-[10px] font-bold mb-1" style={{ color: signalLevelColor(level) }}>
                        Signal No. {level}
                      </p>
                      <ul className="space-y-0.5 pl-1">
                        {levelAreas.map((a, i) => (
                          <li key={i} className="flex items-center gap-2 text-[10px]">
                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: signalLevelColor(level) }} />
                            {a}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
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

// ─── TCB Exposure Summary Modal ──────────────────────────────────────────────
// Per Fabio's request: a view showing, for a given TCB, the list of affected
// areas and how long each was under a wind signal (POST /{tcb_id}/compute-exposure).
function ExposureSummaryModal({
  bulletin, result, isLoading, error, onClose,
}: {
  bulletin: Bulletin;
  result: ComputeExposureResult | null;
  isLoading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[640px] max-h-[80vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0" style={{ background: "#0f1e0f" }}>
          <div className="flex items-center gap-3">
            <MapPinned size={15} className="text-emerald-400" />
            <div>
              <p className="text-[12px] font-bold text-white">Exposure Summary — TCB No. {bulletin.bulletin_count}, {bulletin.typhoon_name}</p>
              <p className="text-[10px] text-white/60">Areas affected and total wind-signal exposure time</p>
            </div>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <p className="text-[11px] text-muted-foreground text-center py-6">Computing exposure summary…</p>
          ) : error ? (
            <div className="px-3 py-2 text-[11px] text-white bg-red-600 rounded-lg">{error}</div>
          ) : !result || result.summaries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground text-center py-6">No affected areas recorded for this bulletin yet.</p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[#166534] text-white">
                  <th className="px-3 py-2 text-left font-semibold">Province</th>
                  <th className="px-3 py-2 text-left font-semibold">Municipality</th>
                  <th className="px-3 py-2 text-left font-semibold">Max Signal</th>
                  <th className="px-3 py-2 text-left font-semibold">Start</th>
                  <th className="px-3 py-2 text-left font-semibold">End</th>
                  <th className="px-3 py-2 text-left font-semibold">Exposure (h)</th>
                  <th className="px-3 py-2 text-left font-semibold">6h+ Eligible</th>
                </tr>
              </thead>
              <tbody>
                {result.summaries.map((s, i) => (
                  <tr key={s.summary_id} className={`border-t border-border ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                    <td className="px-3 py-2">{s.province}</td>
                    <td className="px-3 py-2 font-medium">{s.municipality}</td>
                    <td className="px-3 py-2">No. {s.max_signal_level}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{s.start_time}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{s.end_time}</td>
                    <td className="px-3 py-2 font-semibold">{s.total_exposure_hours.toFixed(1)}</td>
                    <td className="px-3 py-2">
                      {s.is_eligible_6hr
                        ? <span className="text-emerald-600 font-medium">Yes</span>
                        : <span className="text-muted-foreground">No</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-border shrink-0">
          <p className="text-[10px] text-muted-foreground">
            {result ? `${result.boundaries_computed} area(s) computed` : ""}
          </p>
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Close</button>
        </div>
      </div>
    </div>
  );
}

interface MonitoringModuleProps {
  darkMode: boolean;
  selectedBulletin: Bulletin | null;
  onSelectBulletin: (bulletin: Bulletin | null) => void;
  farmsData: FarmsData;
}

export function MonitoringModule({ darkMode, selectedBulletin, onSelectBulletin, farmsData }: MonitoringModuleProps) {
  const [bulletins, setBulletins] = useState<Bulletin[]>([]);
  const [isLoadingBulletins, setIsLoadingBulletins] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Default matches the backend's own ordering (newest issued first) --
  // chronological by issued_at, not by bulletin_count (which resets per
  // typhoon and so isn't a true chronological key across typhoons).
  const [bulletinSortField, setBulletinSortField] = useState<BulletinSortField>("issued_at");
  const [bulletinSortDir, setBulletinSortDir] = useState<SortDir>("desc");

  const [selectedSignals, setSelectedSignals] = useState<TcbSignal[]>([]);
  const [isLoadingSelectedSignals, setIsLoadingSelectedSignals] = useState(false);

  const [viewingTCB, setViewingTCB] = useState<Bulletin | null>(null);
  const [viewingSignals, setViewingSignals] = useState<TcbSignal[]>([]);
  const [isLoadingViewingSignals, setIsLoadingViewingSignals] = useState(false);

  const [exposureBulletin, setExposureBulletin] = useState<Bulletin | null>(null);
  const [exposureResult, setExposureResult] = useState<ComputeExposureResult | null>(null);
  const [isLoadingExposure, setIsLoadingExposure] = useState(false);
  const [exposureError, setExposureError] = useState<string | null>(null);

  const farms = farmsData.farms;
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [insuranceSummary, setInsuranceSummary] = useState<InsuranceSummary | null>(null);
  const [activeTyphoons, setActiveTyphoons] = useState<ActiveTyphoon[]>([]);

  const loadActiveTyphoons = useCallback(async () => {
    try {
      const res = await getActiveTyphoons();
      setActiveTyphoons(res.active_typhoons);
    } catch {
      setActiveTyphoons([]);
    }
  }, []);

  useEffect(() => {
    getAssessments().then(res => setAssessments(res.data)).catch(() => setAssessments([]));
    getInsuranceSummary().then(setInsuranceSummary).catch(() => setInsuranceSummary(null));
    loadActiveTyphoons();
  }, [loadActiveTyphoons]);

  // Most recent assessment per farm_id (list_assessments() is ordered by assessment_date desc).
  const assessmentByFarmId = useMemo(() => {
    const map = new Map<number, Assessment>();
    for (const a of assessments) {
      if (a.farm_id != null && !map.has(a.farm_id)) map.set(a.farm_id, a);
    }
    return map;
  }, [assessments]);

  const farmRows: FarmRow[] = useMemo(
    () => farms.map(f => ({ ...f, assessment: assessmentByFarmId.get(f.farm_id) ?? null })),
    [farms, assessmentByFarmId]
  );

  // "Affected" = has a real computed assessment (wind_velocity set) -- excludes
  // the legacy CSV-import seed rows, which only carry a crop_stage placeholder
  // and never get wind_velocity/period_of_exposure populated (see upload.py).
  const affectedFarmRows = useMemo(() => farmRows.filter(f => f.assessment?.wind_velocity != null), [farmRows]);

  const totalFarms = farms.length;
  const affectedFarms = affectedFarmRows.length;
  const totalArea = affectedFarmRows.reduce((s, f) => s + (f.area_size ?? 0), 0);
  const totalIndemnity = affectedFarmRows.reduce((s, f) => s + (f.assessment?.final_indemnity_payment ?? 0), 0);

  const growthStageData = useMemo(() => {
    const counts = new Map<string, number>();
    for (const f of farmRows) {
      const stage = f.assessment?.crop_stage ?? "Not Assessed";
      counts.set(stage, (counts.get(stage) ?? 0) + 1);
    }
    return Array.from(counts.entries()).map(([name, value], i) => ({
      name, value, color: GROWTH_STAGE_COLORS[i % GROWTH_STAGE_COLORS.length],
    }));
  }, [farmRows]);

  const signalChartData = useMemo(() => {
    const bySignal = new Map<number, { farms: number; area: number }>();
    for (const f of affectedFarmRows) {
      const signal = f.assessment!.wind_velocity!;
      const entry = bySignal.get(signal) ?? { farms: 0, area: 0 };
      entry.farms += 1;
      entry.area += f.area_size ?? 0;
      bySignal.set(signal, entry);
    }
    return Array.from(bySignal.entries())
      .sort(([a], [b]) => a - b)
      .map(([signal, v]) => ({ signal: `Signal ${signal}`, farms: v.farms, area: Math.round(v.area * 10) / 10 }));
  }, [affectedFarmRows]);

  const bulletinTimelineData = useMemo(() => {
    const byDate = new Map<string, number>();
    for (const b of bulletins) {
      if (!b.issued_at) continue;
      const day = b.issued_at.slice(0, 10);
      byDate.set(day, (byDate.get(day) ?? 0) + 1);
    }
    const sortedDays = Array.from(byDate.keys()).sort();
    let cumulative = 0;
    return sortedDays.map(day => {
      cumulative += byDate.get(day)!;
      return { day, bulletins: cumulative };
    });
  }, [bulletins]);

  const loadBulletins = useCallback(async () => {
    setIsLoadingBulletins(true);
    setLoadError(null);
    try {
      const data = await getBulletins();
      setBulletins(data);
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
    try {
      const result = await parseBulletins();
      await loadBulletins();
      await loadActiveTyphoons();
      toast.success(
        result.parsed_count > 0
          ? `Parsed ${result.parsed_count} new bulletin(s).`
          : "No new bulletins to parse — already up to date."
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to parse latest bulletin.");
    } finally {
      setIsParsing(false);
    }
  };

  const handleSelectBulletin = async (b: Bulletin) => {
    const isDeselecting = selectedBulletin?.tcb_id === b.tcb_id;
    onSelectBulletin(isDeselecting ? null : b);
    if (isDeselecting) return;
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

  const handleViewExposure = async (b: Bulletin) => {
    setExposureBulletin(b);
    setExposureResult(null);
    setExposureError(null);
    setIsLoadingExposure(true);
    try {
      setExposureResult(await computeExposure(b.tcb_id));
    } catch (error) {
      setExposureError(error instanceof Error ? error.message : "Failed to compute exposure summary.");
    } finally {
      setIsLoadingExposure(false);
    }
  };

  const handleDownloadBulletinSummary = (b: Bulletin) => {
    const content = [
      "PAGASA TROPICAL CYCLONE BULLETIN",
      `Title: ${b.title}`,
      `Cyclone: ${b.typhoon_name}`,
      `Bulletin No.: ${b.bulletin_count}`,
      `Category: ${b.category ?? "Unknown"}`,
      `Issued: ${formatIssuedAt(b.issued_at)}`,
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

  // Client-side sort for the bulletins table -- separate from the raw
  // `bulletins` array (which stays in API order, newest-issued-first, for
  // `latestBulletin` above) so sorting the table doesn't change what counts
  // as "latest."
  const sortedBulletins = useMemo(() => {
    const indexed = bulletins.map((b, i) => ({ b, i }));
    indexed.sort((x, y) => {
      let cmp: number;
      if (bulletinSortField === "issued_at") {
        cmp = (x.b.issued_at ? Date.parse(x.b.issued_at) : 0) - (y.b.issued_at ? Date.parse(y.b.issued_at) : 0);
      } else {
        const av = x.b[bulletinSortField];
        const cv = y.b[bulletinSortField];
        cmp = typeof av === "number" && typeof cv === "number"
          ? av - cv
          : String(av ?? "").localeCompare(String(cv ?? ""));
      }
      if (cmp === 0) cmp = x.i - y.i; // stable tiebreak
      return bulletinSortDir === "asc" ? cmp : -cmp;
    });
    return indexed.map(({ b }) => b);
  }, [bulletins, bulletinSortField, bulletinSortDir]);

  const handleBulletinSort = (field: BulletinSortField) => {
    if (bulletinSortField === field) {
      setBulletinSortDir(d => (d === "asc" ? "desc" : "asc"));
    } else {
      setBulletinSortField(field);
      setBulletinSortDir(field === "issued_at" ? "desc" : "asc");
    }
  };

  const BulletinSortIcon = ({ field }: { field: BulletinSortField }) =>
    bulletinSortField === field
      ? bulletinSortDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />
      : <ArrowUpDown size={11} className="opacity-30" />;

  const bulletinSortableCols: { label: string; field: BulletinSortField }[] = [
    { label: "Bulletin", field: "bulletin_count" },
    { label: "Typhoon", field: "typhoon_name" },
    { label: "Issued", field: "issued_at" },
    { label: "Category", field: "category" },
    { label: "Max Winds", field: "max_sustained_winds" },
    { label: "Gust", field: "gustiness" },
  ];

  const activeTyphoonNames = activeTyphoons.map(t => t.name).join(", ");

  const statCards = [
    { label:"Active Typhoon",       value: activeTyphoonNames || "N/A", sub:"From PAGASA status page", icon:<Zap size={14} />,        color:"#ef4444", bg:"bg-red-50 dark:bg-red-950/30",     border:"border-red-200 dark:border-red-900" },
    { label:"TCBs Downloaded",      value: bulletins.length, sub:"from PAGASA parser",  icon:<Download size={18} />,   color:"#1e3a5f", bg:"bg-blue-50 dark:bg-blue-950/30",   border:"border-blue-200 dark:border-blue-900" },
    { label:"Affected Farms",       value:`${affectedFarms}/${totalFarms}`,  sub:`${totalArea.toFixed(1)} ha`,icon:<Activity size={18} />, color:"#166534", bg:"bg-green-50 dark:bg-green-950/30", border:"border-green-200 dark:border-green-900" },
    { label:"Est. Total Indemnity", value:`₱${(totalIndemnity/1000).toFixed(0)}K`, sub:"From real computed assessments", icon:<BarChart2 size={18} />, color:"#ca8a04", bg:"bg-amber-50 dark:bg-amber-950/30", border:"border-amber-200 dark:border-amber-900" },
    { label:"Active Insurance",     value: insuranceSummary ? `${insuranceSummary.active_count}/${insuranceSummary.total_count}` : "—", sub:"Within coverage window", icon:<ShieldCheck size={18} />, color:"#7c3aed", bg:"bg-purple-50 dark:bg-purple-950/30", border:"border-purple-200 dark:border-purple-900" },
  ];

  return (
    <div className="h-full overflow-hidden bg-background p-4 flex flex-col gap-4">
      {viewingTCB && (
        <TCBViewerModal
          bulletin={viewingTCB}
          signals={viewingSignals}
          isLoadingSignals={isLoadingViewingSignals}
          onClose={() => setViewingTCB(null)}
        />
      )}
      {exposureBulletin && (
        <ExposureSummaryModal
          bulletin={exposureBulletin}
          result={exposureResult}
          isLoading={isLoadingExposure}
          error={exposureError}
          onClose={() => setExposureBulletin(null)}
        />
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-5 gap-3 shrink-0">
        {statCards.map((c, i) => (
          <div key={i} className={`bg-card border rounded-xl p-4 transition-shadow hover:shadow-md ${c.border}`}>
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

      <div className="grid grid-cols-3 gap-4 flex-1 min-h-0">
        {/* TCB Bulletin List */}
        <div className="col-span-2 bg-card border border-border rounded-xl flex flex-col overflow-hidden min-h-0">
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

          {/* Fills whatever space is left in this card and scrolls internally --
              the page itself no longer scrolls, only this list does. */}
          <div className="flex-1 min-h-0 overflow-auto">
            {isLoadingBulletins && bulletins.length === 0 ? (
              <p className="px-4 py-3 text-[11px] text-muted-foreground">Loading bulletins…</p>
            ) : bulletins.length === 0 ? (
              <p className="px-4 py-3 text-[11px] text-muted-foreground">No bulletins parsed yet.</p>
            ) : (
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 z-10 bg-card">
                  <tr className="bg-muted/50 text-muted-foreground">
                    {bulletinSortableCols.map(col => (
                      <th
                        key={col.field}
                        className="px-3 py-2 text-left font-semibold cursor-pointer hover:bg-muted/80 select-none"
                        onClick={() => handleBulletinSort(col.field)}
                      >
                        <span className="flex items-center gap-1">{col.label}<BulletinSortIcon field={col.field} /></span>
                      </th>
                    ))}
                    <th className="px-3 py-2 text-left font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedBulletins.map(b => (
                    <tr
                      key={b.tcb_id}
                      className={`border-t border-border hover:bg-muted/30 cursor-pointer transition-colors ${selectedBulletin?.tcb_id === b.tcb_id ? "bg-[#166534]/10" : ""}`}
                      onClick={() => handleSelectBulletin(b)}
                    >
                      <td className="px-3 py-2.5 font-semibold">TCB No. {b.bulletin_count}</td>
                      <td className="px-3 py-2.5">{b.typhoon_name}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{formatIssuedAt(b.issued_at)}</td>
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
                          <button
                            onClick={e => { e.stopPropagation(); handleViewExposure(b); }}
                            className="p-1 hover:bg-muted rounded"
                            title="View Exposure Summary (areas & exposure time)"
                          >
                            <MapPinned size={11} className="text-emerald-600" />
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
                  <p className="text-[10px] text-muted-foreground">{formatIssuedAt(selectedBulletin.issued_at)} · {selectedBulletin.category ?? "Unknown category"}</p>
                  <p className="text-[10px] mt-0.5">Max winds: {selectedBulletin.max_sustained_winds ?? "—"} km/h · Gust: {selectedBulletin.gustiness ?? "—"} km/h</p>
                  <p className="text-[10px] text-muted-foreground">
                    Areas: {isLoadingSelectedSignals ? "Loading…" : (uniqueAreas(selectedSignals).join(" • ") || "No signal data recorded")}
                  </p>
                </div>
                <button onClick={() => onSelectBulletin(null)} className="text-muted-foreground text-[10px] hover:text-foreground mt-0.5">✕</button>
              </div>
            </div>
          )}
        </div>

        {/* Right Panel -- System Status moved to Calibration & Settings */}
        <div className="flex flex-col gap-4">
          {/* Growth Stage Distribution -- from real assessment.crop_stage values */}
          <div className="bg-card border border-border rounded-xl p-4 flex-1">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp size={14} className="text-[#ca8a04]" />
              <span className="text-xs font-semibold">Growth Stage Distribution</span>
            </div>
            {growthStageData.length === 0 ? (
              <p className="text-[11px] text-muted-foreground py-6 text-center">No farms yet.</p>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={130}>
                  <PieChart>
                    <Pie data={growthStageData} dataKey="value" cx="50%" cy="50%" innerRadius={30} outerRadius={55} paddingAngle={3}>
                      {growthStageData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Pie>
                    <RTooltip
                      contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
                      formatter={(v: number) => [`${v} farms`, ""]}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex flex-wrap gap-x-2 gap-y-1 mt-1">
                  {growthStageData.map(d => (
                    <span key={d.name} className="flex items-center gap-1 text-[10px]">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: d.color }} />
                      {d.name} ({d.value})
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Charts Row -- from real assessment/bulletin data */}
      <div className="grid grid-cols-2 gap-4 shrink-0">
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 size={14} className="text-[#1e3a5f]" />
            <span className="text-xs font-semibold">Farms by Signal Number</span>
          </div>
          {signalChartData.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-8 text-center">No assessed farms yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={signalChartData} barSize={28}>
                <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#1c2e1c" : "#e5e7eb"} />
                <XAxis dataKey="signal" tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
                <RTooltip
                  contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
                />
                <Bar dataKey="farms"  name="Farms"       fill={SIGNAL_BAR_COLOR} radius={[4,4,0,0]} />
                <Bar dataKey="area"   name="Area (ha)"   fill="#1e3a5f" radius={[4,4,0,0]} />
                <Legend iconSize={10} iconType="square" wrapperStyle={{ fontSize: 10 }} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-card border border-border rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity size={14} className="text-[#ef4444]" />
            <span className="text-xs font-semibold">TCB Download Timeline</span>
          </div>
          {bulletinTimelineData.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-8 text-center">No bulletins with a known issue date yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={150}>
              <LineChart data={bulletinTimelineData}>
                <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#1c2e1c" : "#e5e7eb"} />
                <XAxis dataKey="day" tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize:10 }} axisLine={false} tickLine={false} />
                <RTooltip
                  contentStyle={{ backgroundColor: darkMode ? "#111e11" : "#fff", border:"1px solid #ccc", borderRadius:6, fontSize:11 }}
                />
                <Line type="monotone" dataKey="bulletins" name="Cumulative Bulletins" stroke="#166534" strokeWidth={2} dot={{ r:3 }} />
                <Legend iconSize={10} wrapperStyle={{ fontSize: 10 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

    </div>
  );
}
