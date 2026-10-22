import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Archive, CheckCircle2, RefreshCw } from "lucide-react";
import { archiveAndClear, getArchiveEligibility, ArchiveEligibility, ArchiveResult } from "@/lib/api";

// Archive & Clear (2026-10-22) -- shared by DatabaseBackupModule (admin) and
// AccountSettingsModule (GIS Specialist). Copies every uploaded PABS record and
// polygon into the read-only archive DB, then removes it from the live system.
// The user confirms with their own account password; there is no waiting
// period after the last bulletin. The backend re-checks eligibility and the
// password itself; the disabled button here is only a convenience.

interface ArchiveClearCardProps {
  // Called after the user dismisses the success dialog.
  onArchived?: (result: ArchiveResult) => void;
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export function ArchiveClearCard({ onArchived }: ArchiveClearCardProps) {
  const [state, setState] = useState<ArchiveEligibility | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<ArchiveResult | null>(null);

  const load = useCallback(() => {
    setLoadError(null);
    getArchiveEligibility()
      .then(res => setState(res.data))
      .catch(error => setLoadError(error instanceof Error ? error.message : "Failed to check eligibility."));
  }, []);

  useEffect(load, [load]);

  const closeDialog = () => {
    if (running) return;
    setDialogOpen(false);
    setPassword("");
    setRunError(null);
    if (result) {
      onArchived?.(result);
      setResult(null);
      load();
    }
  };

  const handleConfirm = () => {
    if (!state || !password || running) return;
    setRunning(true);
    setRunError(null);
    archiveAndClear(password)
      .then(res => setResult(res.data))
      .catch(error => {
        setPassword("");
        setRunError(error instanceof Error ? error.message : "Archive & Clear failed.");
      })
      .finally(() => setRunning(false));
  };

  const canRun = !!state?.eligible && state.archive_configured;

  return (
    <div className="bg-card border border-amber-300 rounded-xl p-4">
      <p className="text-xs font-bold mb-2 flex items-center gap-1.5">
        <AlertTriangle size={13} className="text-amber-500" /> Archive & Clear Live Records
      </p>
      <p className="text-[11px] text-muted-foreground mb-3">
        This permanently removes all uploaded PABS data (farmers, farms and their polygons, policies,
        assessments, SAR checks) from the live system. A read-only copy goes to the archive database and a
        full backup to Google Drive. You'll need to re-upload the CSV/GPKG for the next typhoon. Allowed once the
        current records have been assessed for a typhoon; you'll confirm with your password.
      </p>

      {loadError && <p className="text-[11px] text-red-600 mb-2">{loadError}</p>}

      {state && (
        <div className="p-3 rounded-xl bg-muted/40 border border-border text-[11px] space-y-1 mb-3">
          <p>
            Live data: <strong>{state.counts.policies.toLocaleString()}</strong> policies ·{" "}
            <strong>{state.counts.farms.toLocaleString()}</strong> farms ·{" "}
            <strong>{state.counts.farmers.toLocaleString()}</strong> farmers
          </p>
          <p>Assessed for: <strong>{state.typhoons.length ? state.label : "—"}</strong></p>
          {state.typhoons.map(t => (
            <p key={t.typhoon_id} className="text-[10px] text-muted-foreground">
              {t.name} {t.year}: last bulletin {formatDate(t.last_bulletin_at)}
            </p>
          ))}
          {!state.archive_configured && (
            <p className="text-amber-600">The archive database is not configured on the server yet.</p>
          )}
          {state.reason && <p className="text-amber-600">{state.reason}</p>}
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-muted-foreground">
          {state?.eligible ? "Eligible now." : ""}
        </span>
        <button
          onClick={() => setDialogOpen(true)}
          disabled={!canRun}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 disabled:opacity-50 transition-colors"
        >
          <Archive size={12} /> Archive & Clear
        </button>
      </div>

      {dialogOpen && state && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-card border border-amber-300 rounded-xl shadow-2xl p-5 max-w-md w-full">
            {result ? (
              <>
                <div className="flex items-center gap-2 mb-3">
                  <CheckCircle2 size={18} className="text-emerald-600" />
                  <span className="text-sm font-semibold">Archived as #{result.archive_id}</span>
                </div>
                <p className="text-xs text-muted-foreground mb-2">
                  {result.label}: {result.record_count.toLocaleString()} records copied to the archive and cleared from the live system.
                </p>
                <p className="text-[11px] mb-4">
                  Backup <span className="font-mono">{result.dump_file_name}</span>{" "}
                  {result.gdrive_uploaded
                    ? "uploaded to Google Drive."
                    : <span className="text-amber-600">kept on the server only ({result.gdrive_error ?? "Drive upload failed"}).</span>}
                </p>
                <button onClick={closeDialog} className="w-full py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors">
                  Done
                </button>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-3">
                  <AlertTriangle size={18} className="text-amber-500" />
                  <span className="text-sm font-semibold">Archive & Clear — {state.label}</span>
                </div>
                <ul className="text-xs text-muted-foreground mb-3 list-disc pl-4 space-y-0.5">
                  <li>{state.counts.farmers.toLocaleString()} farmers, {state.counts.farms.toLocaleString()} farms and {state.counts.policies.toLocaleString()} policies will be removed from the live system.</li>
                  <li>A full backup is taken first, then everything is copied to the read-only archive.</li>
                  <li>Typhoons, bulletins and user accounts are kept.</li>
                  <li>This cannot be undone in the live system.</li>
                </ul>
                <label className="text-[11px] font-semibold block mb-1">
                  Enter your password to confirm
                </label>
                <input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") handleConfirm(); }}
                  disabled={running}
                  autoFocus
                  className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-red-500 mb-3"
                />
                {runError && <p className="text-[11px] text-red-600 mb-3">{runError}</p>}
                <div className="flex gap-2">
                  <button onClick={closeDialog} disabled={running} className="flex-1 py-1.5 rounded-lg border border-border text-xs hover:bg-muted disabled:opacity-50 transition-colors">
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirm}
                    disabled={running || !password}
                    className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 disabled:opacity-50 transition-colors"
                  >
                    {running ? <><RefreshCw size={12} className="animate-spin" /> Archiving…</> : "Archive & Clear"}
                  </button>
                </div>
                {running && (
                  <p className="text-[10px] text-muted-foreground mt-2">
                    Backing up and copying records — this can take a few minutes. Keep this tab open.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
