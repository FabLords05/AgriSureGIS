import { useEffect, useMemo, useState } from "react";
import { Activity, RefreshCw, ArrowUpDown, ArrowUp, ArrowDown, X } from "lucide-react";
import { getActivityLog, getActivityLogFilters, ActivityLogEntry, ActivityLogFilters } from "@/lib/api";

// New admin tab (2026-08-16) -- records every login, logout, and mutating
// (POST/PUT/PATCH/DELETE) backend call, per Fabio's explicit request. Read-
// only: entries come from main.py's activity_log_middleware + the explicit
// LOGIN/LOGOUT logging in app/api/users.py, nothing here writes to the log.
// Remarks column (2026-10-22): the full sentence of what each action did.
// User / Action filters and sortable headers (2026-10-22, explicit request):
// filtering runs server-side so a narrowed view isn't limited to the newest
// rows; sorting reorders the loaded rows.

const ACTION_STYLES: Record<string, string> = {
  LOGIN:  "bg-blue-100 text-blue-700",
  LOGOUT: "bg-gray-100 text-gray-600",
  POST:   "bg-emerald-100 text-emerald-700",
  PUT:    "bg-amber-100 text-amber-700",
  PATCH:  "bg-amber-100 text-amber-700",
  DELETE: "bg-red-100 text-red-700",
  GET:    "bg-sky-100 text-sky-700",
  INGEST: "bg-teal-100 text-teal-700",
  SYSTEM: "bg-violet-100 text-violet-700",
};

// Rows fetched per view -- the backend's own maximum is 1000.
const FETCH_LIMIT = 500;

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function userLabel(e: ActivityLogEntry): string {
  return e.user_name ?? (e.action === "SYSTEM" ? "System" : "Unknown");
}

// Header click cycles asc -> desc -> off (API order: newest first), same as
// User Management.
type SortKey = "time" | "user" | "summary" | "status";
type SortState = { key: SortKey; dir: "asc" | "desc" } | null;

const SORT_COMPARE: Record<SortKey, (a: ActivityLogEntry, b: ActivityLogEntry) => number> = {
  time:    (a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""),
  user:    (a, b) => userLabel(a).localeCompare(userLabel(b), undefined, { sensitivity: "base" }),
  summary: (a, b) => a.summary.localeCompare(b.summary, undefined, { sensitivity: "base" }),
  status:  (a, b) => a.status_code - b.status_code,
};

interface SortableThProps {
  label: string;
  sortKey: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
}

function SortableTh({ label, sortKey, sort, onSort }: SortableThProps) {
  const active = sort?.key === sortKey;
  const Icon = !active ? ArrowUpDown : sort?.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className="px-3 py-2 text-left font-semibold">
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`flex items-center gap-1 hover:text-foreground transition-colors ${active ? "text-foreground" : ""}`}
        title={`Sort by ${label.toLowerCase()}`}
      >
        {label}
        <Icon size={10} className={active ? "" : "opacity-50"} />
      </button>
    </th>
  );
}

const SELECT_CLASS =
  "border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534] max-w-[16rem]";

export function ActivityLogModule() {
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filterOptions, setFilterOptions] = useState<ActivityLogFilters>({ users: [], action_types: [] });
  const [userId, setUserId] = useState<number | undefined>(undefined);
  const [actionType, setActionType] = useState<string>("");
  const [sort, setSort] = useState<SortState>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const toggleSort = (key: SortKey) => {
    setSort(s => (s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null));
  };

  useEffect(() => {
    getActivityLogFilters()
      .then(res => setFilterOptions(res.data))
      .catch(() => { /* dropdowns just stay empty; the log itself still loads */ });
  }, [reloadKey]);

  useEffect(() => {
    // A slower response for an older filter must not overwrite a newer one.
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getActivityLog({ userId, actionType: actionType || undefined, limit: FETCH_LIMIT })
      .then(res => { if (!cancelled) setEntries(res.data); })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load activity log."); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [userId, actionType, reloadKey]);

  const visibleEntries = useMemo(() => {
    if (!sort) return entries;
    const cmp = SORT_COMPARE[sort.key];
    return [...entries].sort((a, b) => (sort.dir === "asc" ? cmp(a, b) : cmp(b, a)));
  }, [entries, sort]);

  const isFiltered = userId !== undefined || actionType !== "";
  const clearFilters = () => { setUserId(undefined); setActionType(""); };

  return (
    <div className="h-full overflow-auto bg-background p-4">
      <div className="max-w-7xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground flex items-center gap-2">
              <Activity size={18} className="text-[#166534]" /> Activity Log
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Every login, logout, upload, ingestion, change and export, with remarks on exactly what was done, most recent first.</p>
          </div>
          <button
            onClick={() => setReloadKey(k => k + 1)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border text-xs font-semibold hover:bg-muted transition-colors"
          >
            <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>

        <div className="bg-card border border-border rounded-xl overflow-hidden px-4 py-4">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <select
              value={userId ?? ""}
              onChange={e => setUserId(e.target.value === "" ? undefined : Number(e.target.value))}
              className={SELECT_CLASS}
              aria-label="Filter by user"
            >
              <option value="">All users</option>
              {filterOptions.users.map(u => (
                <option key={u.user_id} value={u.user_id}>{u.name} ({u.role})</option>
              ))}
            </select>
            <select
              value={actionType}
              onChange={e => setActionType(e.target.value)}
              className={SELECT_CLASS}
              aria-label="Filter by action"
            >
              <option value="">All actions</option>
              {filterOptions.action_types.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            {isFiltered && (
              <button
                type="button"
                onClick={clearFilters}
                className="flex items-center gap-1 px-3 py-2 rounded-lg border border-border text-[11px] text-muted-foreground hover:bg-muted transition-colors"
              >
                <X size={11} /> Clear filters
              </button>
            )}
            <span className="ml-auto text-[10px] text-muted-foreground">
              {entries.length === FETCH_LIMIT ? `Showing the latest ${FETCH_LIMIT} entries` : `${entries.length} entr${entries.length === 1 ? "y" : "ies"}`}
            </span>
          </div>

          {error && <p className="text-[10px] text-red-600 mb-2">{error}</p>}
          {isLoading && entries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">Loading activity…</p>
          ) : entries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">
              {isFiltered ? "No activity matches the current filters." : "No activity recorded yet."}
            </p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/60 text-muted-foreground">
                  <SortableTh label="Timestamp" sortKey="time" sort={sort} onSort={toggleSort} />
                  <SortableTh label="User" sortKey="user" sort={sort} onSort={toggleSort} />
                  <th className="px-3 py-2 text-left font-semibold">Action</th>
                  <SortableTh label="Summary" sortKey="summary" sort={sort} onSort={toggleSort} />
                  <th className="px-3 py-2 text-left font-semibold">Remarks</th>
                  <SortableTh label="Status" sortKey="status" sort={sort} onSort={toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visibleEntries.map(e => (
                  <tr key={e.log_id} className="border-t border-border align-top">
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">{formatTimestamp(e.created_at)}</td>
                    <td className="px-3 py-2.5 font-medium">
                      {e.user_id !== null ? (
                        <button
                          type="button"
                          onClick={() => setUserId(e.user_id ?? undefined)}
                          className="text-left hover:text-[#166534] hover:underline"
                          title="Show only this user's activity"
                        >
                          {userLabel(e)}
                        </button>
                      ) : (
                        <span className="text-muted-foreground italic">{userLabel(e)}</span>
                      )}
                      {e.user_email && <span className="block text-[9px] text-muted-foreground font-mono">{e.user_email}</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${ACTION_STYLES[e.action] ?? "bg-muted text-muted-foreground"}`}>
                        {e.action}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {filterOptions.action_types.includes(e.summary) ? (
                        <button
                          type="button"
                          onClick={() => setActionType(e.summary)}
                          className="text-left hover:text-[#166534] hover:underline"
                          title="Show only this action"
                        >
                          {e.summary}
                        </button>
                      ) : e.summary}
                      <span className="block text-[9px] text-muted-foreground font-mono">{e.endpoint}</span>
                    </td>
                    <td className="px-3 py-2.5 min-w-[18rem] max-w-md break-words">
                      {e.remarks ?? <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={e.status_code < 400 ? "text-emerald-600 font-semibold" : "text-red-600 font-semibold"}>
                        {e.status_code}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="pb-6" />
      </div>
    </div>
  );
}
