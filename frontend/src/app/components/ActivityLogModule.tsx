import { useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { getActivityLog, ActivityLogEntry } from "@/lib/api";

// New admin tab (2026-08-16) -- records every login, logout, and mutating
// (POST/PUT/PATCH/DELETE) backend call, per Fabio's explicit request. Read-
// only: entries come from main.py's activity_log_middleware + the explicit
// LOGIN/LOGOUT logging in app/api/users.py, nothing here writes to the log.

const ACTION_STYLES: Record<string, string> = {
  LOGIN:  "bg-blue-100 text-blue-700",
  LOGOUT: "bg-gray-100 text-gray-600",
  POST:   "bg-emerald-100 text-emerald-700",
  PUT:    "bg-amber-100 text-amber-700",
  PATCH:  "bg-amber-100 text-amber-700",
  DELETE: "bg-red-100 text-red-700",
};

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-PH", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function ActivityLogModule() {
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setIsLoading(true);
    setError(null);
    getActivityLog()
      .then(res => setEntries(res.data))
      .catch(err => setError(err instanceof Error ? err.message : "Failed to load activity log."))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="h-full overflow-auto bg-background p-4">
      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground flex items-center gap-2">
              <Activity size={18} className="text-[#166534]" /> Activity Log
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Login, logout, and every mutating backend call, most recent first.</p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border text-xs font-semibold hover:bg-muted transition-colors"
          >
            <RefreshCw size={13} className={isLoading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>

        <div className="bg-card border border-border rounded-xl overflow-hidden px-4 py-4">
          {error && <p className="text-[10px] text-red-600 mb-2">{error}</p>}
          {isLoading && entries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">Loading activity…</p>
          ) : entries.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">No activity recorded yet.</p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/60 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-semibold">Timestamp</th>
                  <th className="px-3 py-2 text-left font-semibold">User</th>
                  <th className="px-3 py-2 text-left font-semibold">Action</th>
                  <th className="px-3 py-2 text-left font-semibold">Summary</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(e => (
                  <tr key={e.log_id} className="border-t border-border">
                    <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">{formatTimestamp(e.created_at)}</td>
                    <td className="px-3 py-2.5 font-medium">
                      {e.user_name ?? <span className="text-muted-foreground italic">Unknown</span>}
                      {e.user_email && <span className="block text-[9px] text-muted-foreground font-mono">{e.user_email}</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${ACTION_STYLES[e.action] ?? "bg-muted text-muted-foreground"}`}>
                        {e.action}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {e.summary}
                      <span className="block text-[9px] text-muted-foreground font-mono">{e.endpoint}</span>
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
