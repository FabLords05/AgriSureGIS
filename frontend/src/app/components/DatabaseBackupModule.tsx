import { useState } from "react";
import { Database, RefreshCw, AlertTriangle } from "lucide-react";

// Split out of CalibrationModule.tsx into its own admin tab, beside User
// Management -- previously a collapsed "Database Backup & Restore" section
// nested inside Calibration & Settings. Same state/handlers/dialog, just no
// longer nested in an accordion.

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

export function DatabaseBackupModule() {
  const [autoBackup, setAutoBackup]     = useState(true);
  const [backupRunning, setBackupRunning] = useState(false);
  const [confirm, setConfirm]           = useState<{ msg: string; fn: () => void } | null>(null);

  const handleBackup = () => {
    setBackupRunning(true);
    setTimeout(() => setBackupRunning(false), 3000);
  };

  return (
    <div className="h-full overflow-auto bg-background p-4">
      {confirm && <ConfirmDialog message={confirm.msg} onConfirm={confirm.fn} onCancel={() => setConfirm(null)} />}

      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div>
          <h2 className="font-bold text-foreground flex items-center gap-2">
            <Database size={18} className="text-[#166534]" /> Database Backup & Restore
          </h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">Create, schedule, and restore full system backups.</p>
        </div>

        <div className="bg-card border border-border rounded-xl overflow-hidden px-4 py-4">
          <div className="grid grid-cols-3 gap-3 mb-3">
            {[
              { label:"Last Backup",    value:"30 Oct 2024",   ok:false },
              { label:"Backup Size",    value:"124 MB",        ok:true  },
              { label:"Stored Backups", value:"14 versions",   ok:true  },
            ].map((s,i) => (
              <div key={i} className="bg-muted/40 rounded-lg p-3 border border-border">
                <p className="text-[10px] text-muted-foreground">{s.label}</p>
                <p className={`text-sm font-bold mt-0.5 ${s.ok?"text-foreground":"text-amber-600"}`}>{s.value}</p>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => {
                setConfirm({
                  msg: "This will create a full backup of all farmer records, TCB bulletins, and system settings. Continue?",
                  fn: () => { handleBackup(); setConfirm(null); },
                });
              }}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#1e3a5f] text-white text-[11px] font-medium hover:bg-[#172f4d] transition-colors"
            >
              {backupRunning
                ? <><RefreshCw size={12} className="animate-spin" />Backing up…</>
                : <><Database size={12} />Run Backup Now</>
              }
            </button>
            <button
              onClick={() => setConfirm({
                msg: "This will overwrite all current data with the selected backup. This action cannot be undone. Are you sure?",
                fn: () => setConfirm(null),
              })}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border text-[11px] hover:bg-muted transition-colors text-destructive"
            >
              <RefreshCw size={12} /> Restore from Backup
            </button>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
              <input type="checkbox" checked={autoBackup} onChange={e=>setAutoBackup(e.target.checked)} className="accent-[#166534]" />
              Automatic daily backup at 23:00 PHT
            </label>
          </div>
        </div>

        <div className="pb-6" />
      </div>
    </div>
  );
}
