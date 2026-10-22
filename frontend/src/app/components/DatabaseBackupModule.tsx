import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw, AlertTriangle, Download, Eye, CheckCircle2, XCircle, Cloud, ShieldCheck, Lock } from "lucide-react";
import { toast } from "sonner";
import {
  ArchiveBatch, BackupEntry, BackupOverview,
  downloadArchiveCsv, downloadBackup, getArchives, getBackups, getSystemSettings, runBackupNow, updateAutoBackup,
  verifyBackup,
} from "@/lib/api";
import { ArchiveClearCard } from "./ArchiveClearCard";
import { ArchiveViewer } from "./ArchiveViewer";

// Database Backup & Archive (2026-10-22) -- every control is real now (it was
// a UI-only mock). Backups are pg_dump files on the server + Google Drive;
// Archive & Clear moves the live PABS records into the read-only archive DB.
// Verify (2026-10-22) test-restores a backup -- from the server or from Google
// Drive -- into the separate verification database and compares row counts.
// Overwriting the LIVE database is still never offered in-app: archives are
// viewed, never restored, and a live restore is the DB admin's pg_restore,
// run by hand (.claude/ENV_GUIDE.md).

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
  // backup_id being verified, so only that row shows a spinner
  const [verifying, setVerifying] = useState<number | null>(null);

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

  const handleVerify = (backup: BackupEntry, source: "local" | "gdrive") => {
    setVerifying(backup.backup_id);
    verifyBackup(backup.backup_id, source)
      .then(res => {
        const b = res.data;
        if (b.verify_status === "verified") {
          toast.success(`${b.file_name} restored into the verification database: ${(b.verify_detail?.rows_checked ?? 0).toLocaleString()} rows in ${b.verify_detail?.tables_checked ?? 0} tables match.`);
        } else {
          toast.error(`${b.file_name} did not verify: ${b.verify_detail?.mismatches.length ?? 0} mismatch(es).`);
        }
      })
      .catch(error => toast.error(errorText(error, "Verification failed.")))
      .finally(() => { setVerifying(null); loadBackups(); });
  };

  const askVerify = (backup: BackupEntry, source: "local" | "gdrive") => setConfirm({
    msg: `Restore ${backup.file_name} ${source === "gdrive" ? "from Google Drive " : ""}into the verification database to check it? ` +
      "This replaces whatever the verification database currently holds. The live database is not touched.",
    fn: () => { setConfirm(null); handleVerify(backup, source); },
  });

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
                  { label: "Google Drive",   value: overview == null ? "—" : overview.gdrive_configured ? (overview.encryption_configured ? "Connected · encrypted" : "Connected") : "Not configured", ok: !!overview?.gdrive_configured },
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
                        <th className="py-1.5 pr-3 font-medium">Verified</th>
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
                              ? <span className="inline-flex items-center gap-1" title={b.gdrive_error ?? (b.encrypted ? "Encrypted copy on Google Drive" : "On Google Drive")}>
                                  <CheckCircle2 size={12} className={b.gdrive_error ? "text-amber-500" : "text-emerald-600"} />
                                  {b.encrypted && <Lock size={10} className="text-muted-foreground" />}
                                </span>
                              : b.status === "success" && <span title={b.gdrive_error ?? ""}><Cloud size={12} className="text-amber-500" /></span>}
                          </td>
                          <td className="py-1.5 pr-3 whitespace-nowrap">
                            {b.verify_status === "verified" && (
                              <span className="text-emerald-600" title={`${b.verify_detail?.rows_checked?.toLocaleString() ?? 0} rows / ${b.verify_detail?.tables_checked ?? 0} tables match (${b.verify_detail?.source === "gdrive" ? "Drive copy" : "server copy"})`}>
                                Verified{b.verified_at ? ` · ${formatDate(b.verified_at)}` : ""}
                              </span>
                            )}
                            {b.verify_status === "failed" && (
                              <span className="text-red-600" title={(b.verify_detail?.mismatches ?? []).map(m => m.table ? `${m.table}: expected ${m.expected}, restored ${m.restored ?? "missing"}` : m.error).join("\n")}>
                                Failed ({b.verify_detail?.mismatches.length ?? 0})
                              </span>
                            )}
                            {b.status === "success" && (b.verify_status === "pending" || b.verify_status === null) && (
                              <span className="text-muted-foreground">Not yet</span>
                            )}
                          </td>
                          <td className="py-1.5 text-right whitespace-nowrap space-x-1">
                            {b.status === "success" && overview.verify_db_configured && (b.file_available || b.gdrive_uploaded) && (
                              <button
                                onClick={() => askVerify(b, b.file_available ? "local" : "gdrive")}
                                disabled={verifying !== null}
                                title="Test-restore into the verification database and compare row counts"
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border hover:bg-muted disabled:opacity-50"
                              >
                                {verifying === b.backup_id ? <RefreshCw size={11} className="animate-spin" /> : <ShieldCheck size={11} />} Verify
                              </button>
                            )}
                            {b.status === "success" && overview.verify_db_configured && b.gdrive_uploaded && b.file_available && (
                              <button
                                onClick={() => askVerify(b, "gdrive")}
                                disabled={verifying !== null}
                                title="Download the Google Drive copy and test-restore it"
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border hover:bg-muted disabled:opacity-50"
                              >
                                <Cloud size={11} /> Verify Drive copy
                              </button>
                            )}
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
                Verify restores a backup into the separate verification database and checks every table's row count
                {overview && !overview.verify_db_configured && " (not configured: set BACKUP_VERIFY_DATABASE_URL)"}.
                Replacing the live database is done by the database administrator with pg_restore, outside the app.
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
