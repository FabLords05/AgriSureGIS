import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw, AlertTriangle, Download, Eye, CheckCircle2, XCircle, Cloud } from "lucide-react";
import { toast } from "sonner";
import {
  ArchiveBatch, BackupEntry, BackupOverview,
  downloadArchiveCsv, downloadBackup, getArchives, getBackups, getSystemSettings, runBackupNow, updateAutoBackup,
} from "@/lib/api";
import { ArchiveClearCard } from "./ArchiveClearCard";
import { ArchiveViewer } from "./ArchiveViewer";

// Database Backup & Archive (2026-10-22) -- every control is real now (it was
// a UI-only mock). Backups are pg_dump files on the server + Google Drive;
// Archive & Clear moves the live PABS records into the read-only archive DB.
// "Restore from Backup" was removed on purpose: archives are viewed, never
// restored, and a full restore is Fabio's pg_restore, run by hand.

interface ConfirmDialogProps {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDialog({ message, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-amber-300 rounded-xl shadow-2xl p-5 max-w-sm">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={18} className="text-amber-500" />
          <span className="text-sm font-semibold">Confirm Action</span>
        </div>
        <p className="text-xs text-muted-foreground mb-4">{message}</p>
        <div className="flex gap-2">
          <button onClick={onCancel} className="flex-1 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
          <button onClick={onConfirm} className="flex-1 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-semibold hover:bg-amber-600 transition-colors">Confirm</button>
        </div>
      </div>
    </div>
  );
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const formatDate = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

export function DatabaseBackupModule() {
  const [overview, setOverview] = useState<BackupOverview | null>(null);
  const [archives, setArchives] = useState<ArchiveBatch[] | null>(null);
  const [archivesError, setArchivesError] = useState<string | null>(null);
  const [autoBackup, setAutoBackup] = useState<boolean | null>(null);
  const [backupRunning, setBackupRunning] = useState(false);
  const [confirm, setConfirm] = useState<{ msg: string; fn: () => void } | null>(null);
  const [viewing, setViewing] = useState<ArchiveBatch | null>(null);

  const loadBackups = useCallback(() => {
    getBackups()
      .then(res => setOverview(res.data))
      .catch(error => toast.error(errorText(error, "Failed to load backups.")));
  }, []);

  const loadArchives = useCallback(() => {
    setArchivesError(null);
    getArchives()
      .then(res => setArchives(res.data))
      .catch(error => { setArchives([]); setArchivesError(errorText(error, "Failed to load archives.")); });
  }, []);

  useEffect(() => {
    loadBackups();
    loadArchives();
    getSystemSettings()
      .then(res => setAutoBackup(res.data.auto_backup_enabled))
      .catch(() => setAutoBackup(null));
  }, [loadBackups, loadArchives]);

  const handleBackup = () => {
    setBackupRunning(true);
    runBackupNow()
      .then(res => {
        const b = res.data;
        if (b.gdrive_uploaded) toast.success(`Backup ${b.file_name} saved and uploaded to Google Drive.`);
        else toast.warning(`Backup ${b.file_name} saved on the server only. ${b.gdrive_error ?? ""}`);
      })
      .catch(error => toast.error(errorText(error, "Backup failed.")))
      .finally(() => { setBackupRunning(false); loadBackups(); });
  };

  const handleAutoBackup = (enabled: boolean) => {
    setAutoBackup(enabled);
    updateAutoBackup(enabled)
      .then(res => setAutoBackup(res.data.auto_backup_enabled))
      .catch(error => { setAutoBackup(!enabled); toast.error(errorText(error, "Failed to save the setting.")); });
  };

  const handleDownload = (backup: BackupEntry) => {
    downloadBackup(backup).catch(error => toast.error(errorText(error, "Download failed.")));
  };

  const last = overview?.last_backup ?? null;

  return (
    <div className="h-full overflow-auto bg-background p-4">
      {confirm && <ConfirmDialog message={confirm.msg} onConfirm={confirm.fn} onCancel={() => setConfirm(null)} />}

      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div>
          <h2 className="font-bold text-foreground flex items-center gap-2">
            <Database size={18} className="text-[#166534]" /> Database Backup & Archive
          </h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">Create and schedule full backups, and archive each typhoon's records once it is closed out.</p>
        </div>

        {viewing ? (
          <ArchiveViewer archive={viewing} onClose={() => setViewing(null)} />
        ) : (
          <>
            {/* Backups */}
            <div className="bg-card border border-border rounded-xl overflow-hidden px-4 py-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                {[
                  { label: "Last Backup",    value: last ? formatDate(last.created_at) : "Never", ok: !!last },
                  { label: "Backup Size",    value: formatBytes(last?.size_bytes ?? null),       ok: true },
                  { label: "Stored Backups", value: overview ? `${overview.stored_count} versions` : "—", ok: true },
                  { label: "Google Drive",   value: overview == null ? "—" : overview.gdrive_configured ? "Connected" : "Not configured", ok: !!overview?.gdrive_configured },
                ].map(s => (
                  <div key={s.label} className="bg-muted/40 rounded-lg p-3 border border-border">
                    <p className="text-[10px] text-muted-foreground">{s.label}</p>
                    <p className={`text-sm font-bold mt-0.5 ${s.ok ? "text-foreground" : "text-amber-600"}`}>{s.value}</p>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => setConfirm({
                    msg: "This will create a full backup of all farmer records, TCB bulletins, and system settings, and upload it to Google Drive. Continue?",
                    fn: () => { setConfirm(null); handleBackup(); },
                  })}
                  disabled={backupRunning}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#1e3a5f] text-white text-[11px] font-medium hover:bg-[#172f4d] disabled:opacity-60 transition-colors"
                >
                  {backupRunning
                    ? <><RefreshCw size={12} className="animate-spin" />Backing up…</>
                    : <><Database size={12} />Run Backup Now</>
                  }
                </button>
                <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!autoBackup}
                    disabled={autoBackup === null}
                    onChange={e => handleAutoBackup(e.target.checked)}
                    className="accent-[#166534]"
                  />
                  Automatic daily backup at 23:00 PHT (→ Google Drive)
                </label>
              </div>

              {overview && overview.backups.length > 0 && (
                <div className="mt-4 overflow-x-auto">
                  <table className="text-[11px] w-full">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b border-border">
                        <th className="py-1.5 pr-3 font-medium">Date</th>
                        <th className="py-1.5 pr-3 font-medium">Type</th>
                        <th className="py-1.5 pr-3 font-medium">File</th>
                        <th className="py-1.5 pr-3 font-medium">Size</th>
                        <th className="py-1.5 pr-3 font-medium">Drive</th>
                        <th className="py-1.5 font-medium text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {overview.backups.map(b => (
                        <tr key={b.backup_id} className="border-b border-border/60">
                          <td className="py-1.5 pr-3 whitespace-nowrap">{formatDate(b.created_at)}</td>
                          <td className="py-1.5 pr-3 capitalize">{b.kind}</td>
                          <td className="py-1.5 pr-3 font-mono">
                            {b.status === "failed"
                              ? <span className="text-red-600 flex items-center gap-1" title={b.error ?? ""}><XCircle size={11} /> Failed</span>
                              : b.file_name}
                          </td>
                          <td className="py-1.5 pr-3">{formatBytes(b.size_bytes)}</td>
                          <td className="py-1.5 pr-3">
                            {b.gdrive_uploaded
                              ? <CheckCircle2 size={12} className="text-emerald-600" />
                              : b.status === "success" && <span title={b.gdrive_error ?? ""}><Cloud size={12} className="text-amber-500" /></span>}
                          </td>
                          <td className="py-1.5 text-right">
                            {b.file_available && (
                              <button onClick={() => handleDownload(b)} className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border hover:bg-muted">
                                <Download size={11} /> Dump
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground mt-3">
                Restoring a backup is done by the database administrator with pg_restore, outside the app.
              </p>
            </div>

            {/* Archive & Clear */}
            <ArchiveClearCard onArchived={() => { loadArchives(); loadBackups(); }} />

            {/* Archives */}
            <div className="bg-card border border-border rounded-xl px-4 py-4">
              <p className="text-xs font-bold mb-3">Archives</p>
              {archivesError && <p className="text-[11px] text-amber-600 mb-2">{archivesError}</p>}
              {archives && archives.length === 0 && !archivesError && (
                <p className="text-[11px] text-muted-foreground">No archives yet.</p>
              )}
              {archives && archives.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="text-[11px] w-full">
                    <thead>
                      <tr className="text-left text-muted-foreground border-b border-border">
                        <th className="py-1.5 pr-3 font-medium">Label</th>
                        <th className="py-1.5 pr-3 font-medium">Archived</th>
                        <th className="py-1.5 pr-3 font-medium">By</th>
                        <th className="py-1.5 pr-3 font-medium text-right">Records</th>
                        <th className="py-1.5 pr-3 font-medium">Drive</th>
                        <th className="py-1.5 font-medium text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {archives.map(a => (
                        <tr key={a.archive_id} className="border-b border-border/60">
                          <td className="py-1.5 pr-3 font-semibold">{a.label}</td>
                          <td className="py-1.5 pr-3 whitespace-nowrap">{formatDate(a.archived_at)}</td>
                          <td className="py-1.5 pr-3">{a.archived_by_name ?? "—"}</td>
                          <td className="py-1.5 pr-3 text-right">{a.record_count.toLocaleString()}</td>
                          <td className="py-1.5 pr-3">
                            {a.gdrive_file_id ? <CheckCircle2 size={12} className="text-emerald-600" /> : <Cloud size={12} className="text-amber-500" />}
                          </td>
                          <td className="py-1.5 text-right whitespace-nowrap space-x-1">
                            <button onClick={() => setViewing(a)} className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border hover:bg-muted">
                              <Eye size={11} /> View
                            </button>
                            <button
                              onClick={() => downloadArchiveCsv(a.archive_id).catch(error => toast.error(errorText(error, "Download failed.")))}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border hover:bg-muted"
                            >
                              <Download size={11} /> CSV
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}

        <div className="pb-6" />
      </div>
    </div>
  );
}
