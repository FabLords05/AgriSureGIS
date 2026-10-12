import { useState, useEffect, useCallback, useMemo } from "react";
import { toast } from "sonner";
import {
  Activity, Download, FileDown,
  RefreshCw, Eye, Zap, AlertTriangle,
  X, MapPinned, ShieldCheck,
  ChevronUp, ChevronDown, ArrowUpDown, Check, CheckCircle2, Clock, Wifi, ListChecks
} from "lucide-react";
import {
  Bulletin, TcbSignal, InsuranceSummary, ActiveTyphoon, AssessmentsSummary,
  getBulletins, parseBulletins, getBulletinSignals,
  computeExposure, ComputeExposureResult, getAssessmentsSummary, getInsuranceSummary,
  getActiveTyphoons, TyphoonProgress, getTyphoonProgress, SystemStatus, getSystemStatus,
} from "@/lib/api";

type BulletinSortField = "bulletin_count" | "typhoon_name" | "issued_at" | "category" | "max_sustained_winds" | "gustiness";
type SortDir = "asc" | "desc";

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

const ISLAND_GROUP_LABELS: Record<string, string> = { "0": "Luzon", "1": "Visayas", "2": "Mindanao" };

// PAGASA's raw TCWS text per level (highest first), each with its island-group
// cells -- fallback for when no area resolved to a tbl_tcb_signals row.
function rawTcwsByLevel(tcwsAreas: Bulletin["tcws_areas"]): { level: number; cells: { island: string; text: string }[] }[] {
  if (!tcwsAreas) return [];
  return Object.entries(tcwsAreas)
    .map(([level, byIsland]) => ({
      level: Number(level),
      cells: Object.entries(byIsland)
        .sort((a, b) => Number(a[0]) - Number(b[0]))
        .map(([group, text]) => ({ island: ISLAND_GROUP_LABELS[group] ?? `Group ${group}`, text })),
    }))
    .sort((a, b) => b.level - a.level);
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

function formatClock(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-PH", { timeZone: "Asia/Manila", timeStyle: "short" }).format(date);
}

// Typhoon progress strip (2026-10-11) -- where the tracked typhoon is in the
// workflow, from bulletins collected to the final PABS export. "Current" is
// the first step not done yet.
function TyphoonProgressStrip({ progress, onNavigateToAssessment }: {
  progress: TyphoonProgress;
  onNavigateToAssessment?: () => void;
}) {
  const steps: { title: string; done: boolean; detail: string }[] = [
    {
      title: "Bulletins collected",
      done: progress.bulletin_count > 0,
      detail: `${progress.bulletin_count} TCB${progress.bulletin_count === 1 ? "" : "s"} downloaded`,
    },
    {
      title: "Final TCB issued",
      done: progress.final_bulletin !== null,
      detail: progress.final_bulletin
        ? `TCB #${progress.final_bulletin.bulletin_count} · ${formatIssuedAt(progress.final_bulletin.issued_at)}`
        : "Waiting for PAGASA's final bulletin",
    },
    {
      title: "Exposure computed",
      done: progress.exposure_areas > 0,
      detail: progress.exposure_areas > 0
        ? `${progress.exposure_areas} municipalit${progress.exposure_areas === 1 ? "y" : "ies"}`
        : "Not computed yet",
    },
    {
      title: "Assessment calculated",
      done: progress.assessed_farms > 0,
      detail: progress.assessed_farms > 0
        ? `${progress.assessed_farms} farm${progress.assessed_farms === 1 ? "" : "s"} assessed`
        : "Not calculated yet",
    },
    {
      title: "Exported to PABS",
      done: progress.exported_policies > 0,
      detail: progress.exported_policies > 0
        ? `${progress.exported_policies} polic${progress.exported_policies === 1 ? "y" : "ies"} · ${formatIssuedAt(progress.exported_at)}`
        : "Not exported yet",
    },
  ];
  const currentIndex = steps.findIndex(s => !s.done);

  return (
    <div className="bg-card border border-border rounded-xl shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <ListChecks size={15} className="text-[#166534]" />
          <span className="text-sm font-semibold">{progress.typhoon_name} — Assessment Progress</span>
        </div>
        {progress.in_par ? (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400">
            <span className="w-2 h-2 rounded-full bg-current" /> Inside PAR
          </span>
        ) : (
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-muted text-muted-foreground">
            <span className="w-2 h-2 rounded-full bg-current" /> Exited PAR
          </span>
        )}
      </div>
      <div className="grid grid-cols-5 px-4 py-4">
        {steps.map((s, i) => {
          const isCurrent = i === currentIndex;
          return (
            <div key={s.title} className="relative px-2 text-center">
              {i > 0 && (
                <div className={`absolute top-[14px] -left-1/2 w-full h-[3px] ${s.done || isCurrent ? "bg-[#166534]" : "bg-border"}`} />
              )}
              <div className={`relative z-10 mx-auto mb-1.5 w-[30px] h-[30px] rounded-full flex items-center justify-center text-[12px] font-bold border-[3px] ${
                s.done
                  ? "bg-[#166534] border-[#166534] text-white"
                  : isCurrent
                    ? "bg-card border-[#ca8a04] text-[#ca8a04] ring-4 ring-[#ca8a04]/20"
                    : "bg-card border-border text-muted-foreground"
              }`}>
                {s.done ? <Check size={14} strokeWidth={3} /> : i + 1}
              </div>
              <p className="text-[12px] font-semibold">{s.title}</p>
              <p className="text-[11px] text-muted-foreground">{s.detail}</p>
              {isCurrent && i >= 3 && onNavigateToAssessment && (
                <button onClick={onNavigateToAssessment} className="mt-0.5 text-[11px] font-medium text-[#ca8a04] hover:underline">
                  Go to Assessment &amp; Reporting →
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// System Status panel (2026-10-11) -- PAGASA polling job, newest bulletin,
// and email alert config, from GET /api/system/status. Calibration keeps its
// own Backend API row separately.
function SystemStatusPanel({ status, checkedAt }: { status: SystemStatus | null; checkedAt: string | null }) {
  const parser = status?.parser;
  const parserOk = parser?.last_run_at ? parser.scrape_ok && parser.status_sync_ok : null;
  const rows: { label: string; ok: boolean | null; detail: string; sub?: string }[] = status ? [
    {
      label: "PAGASA Parser",
      ok: parserOk,
      detail: parser?.last_run_at
        ? `Last run ${formatClock(parser.last_run_at)}${parserOk ? "" : " (failed)"}`
        : "Not run yet since restart",
      sub: `Next ${formatClock(parser?.next_run_at)} · every ${parser?.interval_minutes} min`,
    },
    {
      label: "Last bulletin parsed",
      ok: status.last_bulletin ? true : null,
      detail: status.last_bulletin
        ? `TCB #${status.last_bulletin.bulletin_count}${status.last_bulletin.is_final ? " (Final)" : ""} · ${status.last_bulletin.typhoon_name ?? "Unknown"}`
        : "None yet",
      sub: status.last_bulletin ? formatIssuedAt(status.last_bulletin.issued_at) : undefined,
    },
    {
      label: "Email Alerts",
      ok: status.email_alerts.configured,
      detail: status.email_alerts.configured ? "Configured" : "Not configured",
    },
  ] : [];

  return (
    <div className="bg-card border border-border rounded-xl p-4 flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-3">
        <Wifi size={15} className="text-[#166534]" />
        <span className="text-sm font-semibold">System Status</span>
      </div>
      {status === null ? (
        <p className="text-[12px] text-muted-foreground">Status unavailable.</p>
      ) : (
        <div className="divide-y divide-border">
          {rows.map(r => (
            <div key={r.label} className="py-2 flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                {r.ok === null
                  ? <span className="w-3 h-3 rounded-full border-2 border-muted-foreground/50 shrink-0" />
                  : r.ok
                    ? <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />
                    : <AlertTriangle size={13} className="text-amber-500 shrink-0" />}
                <span className="text-[12px]">{r.label}</span>
              </div>
              <div className="text-right">
                <p className="text-[12px] font-medium">{r.detail}</p>
                {r.sub && <p className="text-[11px] text-muted-foreground">{r.sub}</p>}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-auto pt-2 border-t border-border flex items-center gap-1.5">
        <Clock size={11} className="text-muted-foreground" />
        <span className="text-[11px] text-muted-foreground">Checked {checkedAt ?? "—"}</span>
      </div>
    </div>
  );
}

// ─── TCB Detail Viewer Modal ─────────────────────────────────────────────────
function TCBViewerModal({ bulletin, signals, isLoadingSignals, onClose }: { bulletin: Bulletin; signals: TcbSignal[]; isLoadingSignals: boolean; onClose: () => void }) {
  const highestSignal = Math.max(maxSignalLevel(signals), bulletin.max_signal_level ?? 0);
  const signalColor = signalLevelColor(highestSignal);
  const areasByLevel = groupAreasBySignalLevel(signals);
  const rawAreasByLevel = rawTcwsByLevel(bulletin.tcws_areas);
  // max_signal_level 0 = PAGASA explicitly stated no wind signal is hoisted
  // (vs null = no signal information parsed at all).
  const noSignalHoisted = highestSignal === 0 && bulletin.max_signal_level === 0;

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
        : rawAreasByLevel.length
        ? rawAreasByLevel.flatMap(({ level, cells }) => [
            `  Signal No. ${level}:`,
            ...cells.map(c => `    ${c.island}: ${c.text.replace(/\s*\n\s*/g, " ")}`),
          ])
        : noSignalHoisted
        ? ["  No Wind Signal is currently hoisted (per PAGASA)."]
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
                  {isLoadingSignals ? "…" : highestSignal > 0 ? `Signal No. ${highestSignal}` : noSignalHoisted ? "No Wind Signal Is Raised" : "No Signal Data"}
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
              ) : rawAreasByLevel.length ? (
                <div className="space-y-2.5">
                  {rawAreasByLevel.map(({ level, cells }) => (
                    <div key={level}>
                      <p className="text-[10px] font-bold mb-1" style={{ color: signalLevelColor(level) }}>
                        Signal No. {level}
                      </p>
                      <ul className="space-y-0.5 pl-1">
                        {cells.map(({ island, text }) => (
                          <li key={island} className="flex items-start gap-2 text-[10px]">
                            <span className="w-1.5 h-1.5 rounded-full shrink-0 mt-1" style={{ background: signalLevelColor(level) }} />
                            <span><span className="font-semibold">{island}:</span> {text.replace(/\s*\n\s*/g, " ")}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : noSignalHoisted ? (
                <p className="text-[10px] text-muted-foreground">No Wind Signal is Currently Listed.</p>
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
  onNavigateToAssessment?: () => void;
}

const SYSTEM_STATUS_REFRESH_MS = 60_000;

export function MonitoringModule({ selectedBulletin, onSelectBulletin, onNavigateToAssessment }: MonitoringModuleProps) {
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

  const [assessmentsSummary, setAssessmentsSummary] = useState<AssessmentsSummary | null>(null);
  const [insuranceSummary, setInsuranceSummary] = useState<InsuranceSummary | null>(null);
  const [activeTyphoons, setActiveTyphoons] = useState<ActiveTyphoon[]>([]);
  const [typhoonProgress, setTyphoonProgress] = useState<TyphoonProgress | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [systemStatusCheckedAt, setSystemStatusCheckedAt] = useState<string | null>(null);

  const loadSystemStatus = useCallback(async () => {
    try {
      setSystemStatus(await getSystemStatus());
    } catch {
      setSystemStatus(null);
    } finally {
      setSystemStatusCheckedAt(formatClock(new Date().toISOString()));
    }
  }, []);

  // Refreshed every minute so the parser's last/next run stays current
  // while the dashboard is left open.
  useEffect(() => {
    loadSystemStatus();
    const id = setInterval(loadSystemStatus, SYSTEM_STATUS_REFRESH_MS);
    return () => clearInterval(id);
  }, [loadSystemStatus]);

  const loadActiveTyphoons = useCallback(async () => {
    try {
      const res = await getActiveTyphoons();
      setActiveTyphoons(res.active_typhoons);
    } catch {
      setActiveTyphoons([]);
    }
  }, []);

  // Stat cards + charts all come from one server-side aggregate now
  // (2026-08-18, stage 2 of the on-demand-pagination redesign -- see
  // .claude/FUNCTION_CHANGES.md) instead of reducing over the full farms
  // array + a separate unpaginated GET /assessments/ fetch client-side.
  useEffect(() => {
    getAssessmentsSummary().then(setAssessmentsSummary).catch(() => setAssessmentsSummary(null));
    getInsuranceSummary().then(setInsuranceSummary).catch(() => setInsuranceSummary(null));
    loadActiveTyphoons();
  }, [loadActiveTyphoons]);

  const totalFarms = assessmentsSummary?.total_farms ?? 0;
  const affectedFarms = assessmentsSummary?.affected_farms ?? 0;
  const totalArea = assessmentsSummary?.total_area ?? 0;

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
      loadSystemStatus();
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

  // TCBs Downloaded is scoped to one typhoon, not a lifetime total -- the
  // first/primary active typhoon if there is one (per Fabio: two storms
  // active at once is rare enough not to bother summing/listing separately),
  // falling back to the most recently-issued bulletin's typhoon once nothing
  // is active anymore, so the count + alert below still has something to
  // point at right after a typhoon closes out. Matched by typhoon_id, not
  // name -- PAGASA reuses local names across seasons.
  const primaryTyphoonId = activeTyphoons[0]?.typhoon_id ?? bulletins[0]?.typhoon_id ?? null;
  const primaryTyphoonName = activeTyphoons[0]?.name ?? bulletins[0]?.typhoon_name ?? null;
  const primaryTyphoonBulletins = primaryTyphoonId !== null
    ? bulletins.filter(b => b.typhoon_id === primaryTyphoonId)
    : [];
  // "Ready for assessment" = PAGASA has issued this typhoon's final bulletin
  // (the stored is_final marker -- trailing "F" on the bulletin number, or an
  // LPA bulletin). Replaces the earlier "no longer on PAGASA's active list"
  // signal, which was only a stand-in while is_final wasn't persisted: a
  // storm drops off the active list even if its final TCB was never
  // downloaded. See .claude/FUNCTION_CHANGES.md (2026-10-09).
  const typhoonDoneCollecting = primaryTyphoonBulletins.some(b => b.is_final);

  // Progress strip follows the same typhoon as the TCBs Downloaded card, and
  // refetches when that typhoon's bulletin count or PAR status changes.
  const primaryTyphoonInPar = activeTyphoons.some(t => t.typhoon_id === primaryTyphoonId);
  useEffect(() => {
    if (primaryTyphoonId === null) {
      setTyphoonProgress(null);
      return;
    }
    let cancelled = false;
    getTyphoonProgress(primaryTyphoonId)
      .then(p => { if (!cancelled) setTyphoonProgress(p); })
      .catch(() => { if (!cancelled) setTyphoonProgress(null); });
    return () => { cancelled = true; };
  }, [primaryTyphoonId, primaryTyphoonBulletins.length, primaryTyphoonInPar]);

  const statCards: {
    label: string; value: string | number; sub: string; icon: React.ReactNode;
    color: string; bg: string; border: string; alert: string | null;
  }[] = [
    { label:"Active Typhoon",   value: activeTyphoonNames || "N/A", sub:"From PAGASA status page", icon:<Zap size={18} />,        color:"#ef4444", bg:"bg-red-50 dark:bg-red-950/30",     border:"border-red-200 dark:border-red-900", alert: null },
    {
      label:"TCBs Downloaded",
      value: primaryTyphoonBulletins.length,
      sub: primaryTyphoonName ? `for ${primaryTyphoonName}` : "No tracked typhoon yet",
      icon: typhoonDoneCollecting ? <AlertTriangle size={18} /> : <Download size={18} />,
      color: typhoonDoneCollecting ? "#d97706" : "#1e3a5f",
      bg: typhoonDoneCollecting ? "bg-amber-50 dark:bg-amber-950/30" : "bg-blue-50 dark:bg-blue-950/30",
      border: typhoonDoneCollecting ? "border-amber-300 dark:border-amber-700" : "border-blue-200 dark:border-blue-900",
      alert: typhoonDoneCollecting ? "Ready for assessment" : null,
    },
    { label:"Affected Farms",   value:`${affectedFarms}/${totalFarms}`,  sub:`${totalArea.toFixed(1)} ha`,icon:<Activity size={18} />, color:"#166534", bg:"bg-green-50 dark:bg-green-950/30", border:"border-green-200 dark:border-green-900", alert: null },
    { label:"Active Insurance", value: insuranceSummary ? `${insuranceSummary.active_count}/${insuranceSummary.total_count}` : "—", sub:"In coverage · not yet used", icon:<ShieldCheck size={18} />, color:"#7c3aed", bg:"bg-purple-50 dark:bg-purple-950/30", border:"border-purple-200 dark:border-purple-900", alert: null },
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

      {/* Stat Cards -- Est. Total Indemnity and Growth Stage/TCB Timeline
          charts removed per Fabio's redesign; TCBs Downloaded brought back
          but rescoped to one typhoon with a "Ready for assessment" alert. */}
      <div className="grid grid-cols-4 gap-4 shrink-0">
        {statCards.map((c, i) => (
          <div key={i} className={`bg-card border rounded-xl p-5 transition-shadow hover:shadow-md ${c.border}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[12px] text-muted-foreground uppercase tracking-wide">{c.label}</p>
                <p className="text-3xl font-bold mt-1" style={{ color: c.color }}>{c.value}</p>
                <p className="text-[11px] text-muted-foreground mt-1">{c.sub}</p>
              </div>
              <div className="w-14 h-14 rounded-xl flex items-center justify-center" style={{ backgroundColor: c.color + "20", color: c.color }}>
                {c.icon}
              </div>
            </div>
            {c.alert && (
              <div className="mt-3 flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300">
                <AlertTriangle size={12} className="shrink-0" />
                <span className="text-[10px] font-medium leading-tight">{c.alert}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {typhoonProgress && (
        <TyphoonProgressStrip progress={typhoonProgress} onNavigateToAssessment={onNavigateToAssessment} />
      )}

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

        {/* System Status took the slot Farms by Signal Number had (removed
            2026-10-11 per Cristian; Growth Stage Distribution and the TCB
            Download Timeline went 2026-10-09). */}
        <SystemStatusPanel status={systemStatus} checkedAt={systemStatusCheckedAt} />
      </div>

    </div>
  );
}
