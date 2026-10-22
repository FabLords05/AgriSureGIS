import { AlertCircle, AlertTriangle } from "lucide-react";
import { AreaExposureSummary, TyphoonExposure } from "@/lib/api";

// Shared by the Main Dashboard's Exposure Summary and Assessment &
// Reporting's Areas Affected (2026-10-22), so both always show the same
// backend-calculated values (GET /api/bulletins/typhoon/{id}/exposure).
// Exposure = Signal 1 + ... + Signal 5 hours; it is never recomputed here.

const ISLAND_GROUP_LABELS: Record<number, string> = { 0: "Luzon", 1: "Visayas", 2: "Mindanao" };
const SIGNAL_LEVELS = [1, 2, 3, 4, 5] as const;

function signalHours(area: AreaExposureSummary, level: (typeof SIGNAL_LEVELS)[number]): number {
  return area[`signal_${level}_hours`];
}

function formatHours(hours: number): string {
  // Partial hours are kept: 2.5 -> "2.5", 12 -> "12"
  return `${Number.isInteger(hours) ? hours : hours.toFixed(2).replace(/0$/, "")} hrs`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-PH", { timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short" }).format(d);
}

export function ExposureTable({
  exposure, showIslandGroup = false, headerColor = "#166534",
}: {
  exposure: TyphoonExposure;
  showIslandGroup?: boolean;
  headerColor?: string;
}) {
  const areas = exposure.areas;
  const partial = exposure.unresolved_clauses.filter(u => u.reason === "partial_coverage_no_list");
  const unmatched = exposure.unresolved_clauses.filter(u => u.reason === "no_boundary_match");
  const hasOpen = areas.some(a => a.has_open_interval);
  const hasGap = areas.some(a => a.has_long_gap);

  return (
    <div className="flex flex-col gap-2">
      {areas.length === 0 ? (
        <p className="text-[11px] text-muted-foreground text-center py-6">No affected municipalities recorded for this typhoon yet.</p>
      ) : (
        <table className="w-full text-[10px]">
          <thead className="sticky top-0 z-10">
            <tr className="text-white" style={{ background: headerColor }}>
              {showIslandGroup && <th className="px-2 py-2 text-left font-semibold">Island Group</th>}
              <th className="px-2 py-2 text-left font-semibold">Province</th>
              <th className="px-2 py-2 text-left font-semibold">Municipality</th>
              <th className="px-2 py-2 text-center font-semibold">Max Signal</th>
              {SIGNAL_LEVELS.map(level => (
                <th key={level} className="px-2 py-2 text-right font-semibold whitespace-nowrap">Signal {level}</th>
              ))}
              <th className="px-2 py-2 text-right font-semibold">Exposure</th>
              <th className="px-2 py-2 text-left font-semibold">Start</th>
              <th className="px-2 py-2 text-left font-semibold">End</th>
            </tr>
          </thead>
          <tbody>
            {areas.map((a, i) => (
              <tr key={a.summary_id} className={`border-t border-border ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                {showIslandGroup && (
                  <td className="px-2 py-1.5 text-muted-foreground">{a.island_group !== null ? ISLAND_GROUP_LABELS[a.island_group] ?? "—" : "—"}</td>
                )}
                <td className="px-2 py-1.5">{a.province}</td>
                <td className="px-2 py-1.5 font-medium">
                  {a.municipality}
                  {a.has_open_interval && <span className="ml-1 text-[9px] text-blue-600" title="Still under a signal in the latest bulletin; counted up to that bulletin's issue time, and extended when a later bulletin arrives.">(ongoing)</span>}
                  {a.has_long_gap && <span className="ml-1 text-[9px] text-amber-600" title="Counted across a gap of more than 12 hours between consecutive bulletins.">(gap)</span>}
                </td>
                <td className="px-2 py-1.5 text-center font-semibold">{a.max_signal_level}</td>
                {SIGNAL_LEVELS.map(level => {
                  const h = signalHours(a, level);
                  return (
                    <td key={level} className={`px-2 py-1.5 text-right tabular-nums whitespace-nowrap ${h === 0 ? "text-muted-foreground" : ""}`}>
                      {formatHours(h)}
                    </td>
                  );
                })}
                <td className="px-2 py-1.5 text-right tabular-nums whitespace-nowrap font-bold">{formatHours(a.total_exposure_hours)}</td>
                <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">{formatDateTime(a.start_time)}</td>
                <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">{formatDateTime(a.end_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {partial.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200">
          <AlertTriangle size={12} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="text-[10px] text-amber-800 dark:text-amber-300">
            <p className="font-semibold">Partial coverage without a town list — no municipalities assigned:</p>
            <ul className="list-disc ml-4">
              {partial.map((u, i) => (
                <li key={i}>TCB No. {u.bulletin_count ?? "?"}, Signal {u.signal_level}: "{u.clause}"</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {unmatched.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-muted/40 border border-border">
          <AlertCircle size={12} className="text-muted-foreground shrink-0 mt-0.5" />
          <p className="text-[10px] text-muted-foreground">
            Not matched to a municipality: {unmatched.map(u => `"${u.clause}" (TCB No. ${u.bulletin_count ?? "?"}, Signal ${u.signal_level})`).join("; ")}
          </p>
        </div>
      )}
      {exposure.bulletins_without_issue_time.length > 0 && (
        <p className="text-[10px] text-amber-700">
          Left out (issue time unreadable): TCB No. {exposure.bulletins_without_issue_time.join(", ")}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground leading-snug">
        <span className="font-semibold">Exposure</span> = Signal 1 + Signal 2 + Signal 3 + Signal 4 + Signal 5 hours.{" "}
        {exposure.methodology}
        {hasOpen && " (ongoing) = still under a signal in the latest bulletin."}
        {hasGap && " (gap) = counted across a >12h gap between bulletins."}
      </p>
    </div>
  );
}
