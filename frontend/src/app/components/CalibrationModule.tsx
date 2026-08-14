import { useEffect, useState } from "react";
import {
  Settings, Key, Database, Users, Shield, Save, AlertTriangle,
  ChevronDown, ChevronRight, RefreshCw, Trash2, Plus, CheckCircle2,
  Server, Bell, Clock, ToggleLeft, ToggleRight, Eye, EyeOff, DollarSign, Wifi
} from "lucide-react";
import { DAMAGE_FACTORS, GrowthStage } from "./mockData";
import { getParserSettings, updateParserSettings, getUsers, createUser, updateUser, SystemUser } from "@/lib/api";

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

function Section({ title, icon, children, defaultOpen = true }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-2.5 px-4 py-3 hover:bg-muted/40 transition-colors text-left"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-[#166534]">{icon}</span>
        <span className="text-sm font-semibold flex-1">{title}</span>
        {open ? <ChevronDown size={14} className="text-muted-foreground" /> : <ChevronRight size={14} className="text-muted-foreground" />}
      </button>
      {open && <div className="border-t border-border px-4 py-4">{children}</div>}
    </div>
  );
}

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

interface CalibrationModuleProps {
  coverageRatePerHa: number;
  onCoverageRateChange: (rate: number) => void;
}

// Only two roles actually mean anything anywhere else in the app (Login's
// role toggle, Registration's own restriction) -- matches
// backend/app/api/users.py's ALLOWED_ROLES, not the prototype's wider
// 4-option dropdown (Data Analyst/Field Supervisor had no backing
// permission logic anywhere).
const USER_ROLES = ["GIS Specialist", "System Administrator"] as const;

export function CalibrationModule({ coverageRatePerHa, onCoverageRateChange }: CalibrationModuleProps) {
  const [damageFactor, setDamageFactor] = useState<Record<GrowthStage, Record<number, number>>>(
    JSON.parse(JSON.stringify(DAMAGE_FACTORS))
  );
  const [geeProjectId, setGeeProjectId] = useState("pcic-bicol-gee-2024");
  const [geeApiKey, setGeeApiKey]       = useState("AIzaSyPCIC-BICOL-GEE-2024-DEMO-KEY");
  const [showGeeKey, setShowGeeKey]     = useState(false);
  const [sessionTimeout, setSessionTimeout] = useState(5);
  const [autoBackup, setAutoBackup]     = useState(true);
  const [emailAlerts, setEmailAlerts]   = useState(true);
  const [parserInterval, setParserInterval] = useState(180); // minutes -- was 3 (hours) until 2026-08-10
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [confirm, setConfirm]           = useState<{ msg: string; fn: () => void } | null>(null);
  const [backupRunning, setBackupRunning] = useState(false);
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);

  // User management modals
  const [editingUser, setEditingUser] = useState<SystemUser | null>(null);
  const [addingUser, setAddingUser]   = useState(false);
  const [newUser, setNewUser]         = useState({ name:"", role:"GIS Specialist", email:"", password:"" });
  const [userActionError, setUserActionError] = useState<string | null>(null);

  const loadUsers = () => {
    setIsLoadingUsers(true);
    setUsersError(null);
    getUsers()
      .then(res => setUsers(res.data))
      .catch(error => setUsersError(error instanceof Error ? error.message : "Failed to load users."))
      .finally(() => setIsLoadingUsers(false));
  };

  // Backend API status -- real, not mock. Piggybacks on the getParserSettings()
  // call this screen already makes on mount, rather than firing an extra
  // request just to check connectivity.
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [lastCheck, setLastCheck] = useState<string | null>(null);

  useEffect(() => {
    getParserSettings()
      .then(s => {
        setParserInterval(s.polling_interval_minutes);
        setBackendOk(true);
      })
      .catch(() => setBackendOk(false)) // keep the default of 3 if the backend isn't reachable yet
      .finally(() => setLastCheck(new Date().toLocaleTimeString()));
    loadUsers();
  }, []);

  const handleSave = () => {
    updateParserSettings(parserInterval).catch(() => {});
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2500);
  };

  const handleBackup = () => {
    setBackupRunning(true);
    setTimeout(() => setBackupRunning(false), 3000);
  };

  const handleDeleteUser = (id: number) => {
    setConfirm({
      msg: "Are you sure you want to deactivate this user account? This action can be reversed by an administrator.",
      fn: () => {
        setUserActionError(null);
        updateUser(id, { is_active: false })
          .then(res => setUsers(u => u.map(x => x.user_id === id ? res.data : x)))
          .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to deactivate user."))
          .finally(() => setConfirm(null));
      },
    });
  };

  const handleSaveEditUser = () => {
    if (!editingUser) return;
    setUserActionError(null);
    updateUser(editingUser.user_id, {
      name: editingUser.name,
      email: editingUser.email,
      role: editingUser.role,
      is_active: editingUser.is_active,
    })
      .then(res => {
        setUsers(u => u.map(x => x.user_id === editingUser.user_id ? res.data : x));
        setEditingUser(null);
      })
      .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to save changes."));
  };

  const handleAddUser = () => {
    if (!newUser.name.trim() || !newUser.email.trim()) return;
    setUserActionError(null);
    createUser(newUser)
      .then(res => {
        setUsers(u => [...u, res.data]);
        setNewUser({ name:"", role:"GIS Specialist", email:"", password:"" });
        setAddingUser(false);
      })
      .catch(error => setUserActionError(error instanceof Error ? error.message : "Failed to create user."));
  };

  const stages: GrowthStage[] = ["Seedling","Vegetative","Reproductive","Ripening"];
  const signals = [1,2,3];

  return (
    <div className="h-full overflow-auto bg-background p-4">
      {confirm && <ConfirmDialog message={confirm.msg} onConfirm={confirm.fn} onCancel={() => setConfirm(null)} />}

      {/* Edit User Modal */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-[400px] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <p className="text-sm font-bold">Edit User Account</p>
              <button onClick={() => setEditingUser(null)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>
            <div className="p-4 space-y-3">
              {[
                { label:"Full Name", key:"name" as const, type:"text" },
                { label:"Email",     key:"email" as const, type:"email" },
              ].map(f => (
                <div key={f.key}>
                  <label className="text-[11px] font-semibold block mb-1">{f.label}</label>
                  <input
                    type={f.type}
                    value={editingUser[f.key]}
                    onChange={e => setEditingUser({ ...editingUser, [f.key]: e.target.value })}
                    className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  />
                </div>
              ))}
              <div>
                <label className="text-[11px] font-semibold block mb-1">Role</label>
                <select
                  value={editingUser.role}
                  onChange={e => setEditingUser({ ...editingUser, role: e.target.value })}
                  className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                >
                  {USER_ROLES.map(r => <option key={r}>{r}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="activeToggle" checked={editingUser.is_active} onChange={e => setEditingUser({ ...editingUser, is_active: e.target.checked })} className="accent-[#166534]" />
                <label htmlFor="activeToggle" className="text-[11px]">Account Active</label>
              </div>
              {userActionError && <p className="text-[10px] text-red-600">{userActionError}</p>}
            </div>
            <div className="flex gap-2 px-4 py-3 border-t border-border justify-end">
              <button onClick={() => setEditingUser(null)} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
              <button onClick={handleSaveEditUser} className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors">
                <Save size={11} /> Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add User Modal */}
      {addingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-2xl shadow-2xl w-[400px] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <p className="text-sm font-bold">Add New User Account</p>
              <button onClick={() => setAddingUser(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>
            <div className="p-4 space-y-3">
              {[
                { label:"Full Name",        key:"name" as const,     type:"text"     },
                { label:"Email Address",    key:"email" as const,    type:"email"    },
                { label:"Temp. Password",   key:"password" as const, type:"password" },
              ].map(f => (
                <div key={f.key}>
                  <label className="text-[11px] font-semibold block mb-1">{f.label}</label>
                  <input
                    type={f.type}
                    value={newUser[f.key]}
                    onChange={e => setNewUser({ ...newUser, [f.key]: e.target.value })}
                    placeholder={f.label}
                    className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                  />
                </div>
              ))}
              <div>
                <label className="text-[11px] font-semibold block mb-1">Role</label>
                <select
                  value={newUser.role}
                  onChange={e => setNewUser({ ...newUser, role: e.target.value })}
                  className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                >
                  {USER_ROLES.map(r => <option key={r}>{r}</option>)}
                </select>
              </div>
              {(!newUser.name.trim() || !newUser.email.trim()) && (
                <p className="text-[10px] text-amber-600">Name and email are required.</p>
              )}
              {userActionError && <p className="text-[10px] text-red-600">{userActionError}</p>}
            </div>
            <div className="flex gap-2 px-4 py-3 border-t border-border justify-end">
              <button onClick={() => setAddingUser(false)} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Cancel</button>
              <button
                onClick={handleAddUser}
                disabled={!newUser.name.trim() || !newUser.email.trim()}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] disabled:opacity-50 transition-colors"
              >
                <Plus size={11} /> Create Account
              </button>
            </div>
          </div>
        </div>
      )}

      {savedSuccess && (
        <div className="fixed top-16 right-4 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-50 border border-emerald-200 shadow-xl">
          <CheckCircle2 size={14} className="text-emerald-600" />
          <span className="text-xs font-medium text-emerald-700">Settings saved successfully.</span>
        </div>
      )}

      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground flex items-center gap-2">
              <Settings size={18} className="text-[#166534]" /> Calibration & Settings
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Configure system parameters, credentials, and user access.</p>
          </div>
          <button
            onClick={handleSave}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
          >
            <Save size={13} /> Save All Settings
          </button>
        </div>

        {/* System Status -- moved here from Monitoring & Extraction */}
        <Section title="System Status" icon={<Wifi size={15} />}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {backendOk
                ? <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
                : <AlertTriangle size={12} className="text-amber-500 shrink-0" />
              }
              <span className="text-[11px]">Backend API</span>
            </div>
            <span className="text-[10px] text-muted-foreground">
              {backendOk === null ? "Checking…" : backendOk ? "Connected" : "Unreachable"}
            </span>
          </div>
          <div className="mt-3 pt-2 border-t border-border flex items-center gap-1.5">
            <Clock size={10} className="text-muted-foreground" />
            <span className="text-[10px] text-muted-foreground">Last check: {lastCheck ?? "—"}</span>
          </div>
        </Section>

        {/* Coverage Parameters */}
        <Section title="RSBSA Coverage Rate (Sum Insured)" icon={<DollarSign size={15} />}>
          <p className="text-[11px] text-muted-foreground mb-4">
            The RSBSA fixed coverage rate is <strong>₱25,000 per hectare</strong> for all rice farmers. This is the only configurable rate — no crop type premium distinction. Changes apply immediately to the Assessment module.
          </p>
          <div className="flex gap-4 items-end mb-4">
            <div className="flex-1 max-w-xs">
              <label className="text-[11px] font-semibold block mb-1.5">
                RSBSA Rate — Rice <span className="text-muted-foreground font-normal">(₱ per hectare)</span>
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-[11px]">₱</span>
                <input
                  type="number"
                  min={1000}
                  max={100000}
                  step={500}
                  value={coverageRatePerHa}
                  onChange={e => onCoverageRateChange(Number(e.target.value))}
                  className="w-full border border-border rounded-lg pl-7 pr-3 py-2.5 text-[12px] font-bold focus:outline-none focus:border-[#166534] bg-background"
                />
              </div>
              <p className="text-[9px] text-muted-foreground mt-1">PCIC RSBSA fixed rate. Applies to all rice farmer records.</p>
            </div>
            <div className="text-[10px] text-muted-foreground pb-7">
              Default: <strong className="text-[#166534]">₱25,000/ha</strong>
            </div>
          </div>
          <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200">
            <p className="text-[11px] font-semibold text-amber-700 mb-1">Live Preview — Impact at Current Rate</p>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="text-[9px] text-muted-foreground">Rate per Hectare</p>
                <p className="text-base font-black text-amber-700">₱{coverageRatePerHa.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-[9px] text-muted-foreground">Sample: 2.5 ha</p>
                <p className="text-base font-black text-[#166534]">₱{(2.5 * coverageRatePerHa).toLocaleString()}</p>
              </div>
              <div>
                <p className="text-[9px] text-muted-foreground">At 40% ind. factor</p>
                <p className="text-base font-black text-[#1e3a5f]">₱{(2.5 * coverageRatePerHa * 0.4).toLocaleString()}</p>
              </div>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground mt-2">
            Per-record overrides can be applied in the Assessment module by clicking the edit icon on any row's Sum Insured column.
          </p>
        </Section>

        {/* Damage Factor Table */}
        <Section title="Signal Damage Factor Table" icon={<Settings size={15} />}>
          <p className="text-[11px] text-muted-foreground mb-3">
            Edit the percentage damage factor applied per growth stage and signal number. Changes take effect on the next analysis run.
          </p>
          <div className="overflow-x-auto">
            <table className="text-[11px] w-full">
              <thead>
                <tr className="bg-[#166534] text-white">
                  <th className="px-3 py-2 text-left font-semibold">Growth Stage</th>
                  {signals.map(s => (
                    <th key={s} className="px-3 py-2 text-center font-semibold">
                      Signal No. {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stages.map(stage => (
                  <tr key={stage} className="border-t border-border hover:bg-muted/30">
                    <td className="px-3 py-2.5 font-semibold">{stage}</td>
                    {signals.map(sig => (
                      <td key={sig} className="px-3 py-2.5 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <input
                            type="number"
                            min={0} max={100}
                            value={damageFactor[stage][sig]}
                            onChange={e => setDamageFactor(df => ({
                              ...df,
                              [stage]: { ...df[stage], [sig]: Number(e.target.value) }
                            }))}
                            className="w-16 text-center border border-border rounded px-2 py-1 bg-background text-[11px] focus:outline-none focus:border-[#166534]"
                          />
                          <span className="text-muted-foreground">%</span>
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-muted-foreground mt-2">
            Source: PCIC Standard Indemnification Guidelines — values must match official PCIC forms for Finance Division compatibility.
          </p>
        </Section>

        {/* GEE Credentials */}
        <Section title="Google Earth Engine Credentials" icon={<Key size={15} />}>
          <p className="text-[11px] text-muted-foreground mb-3">
            Configure Google Cloud Project credentials for SAR (Synthetic Aperture Radar) imagery analysis via Google Earth Engine.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[11px] font-medium block mb-1">GCP Project ID</label>
              <input
                value={geeProjectId}
                onChange={e => setGeeProjectId(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                placeholder="your-gcp-project-id"
              />
            </div>
            <div>
              <label className="text-[11px] font-medium block mb-1">EEC Capacity Allocated</label>
              <input
                defaultValue="1000"
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                placeholder="e.g. 1000"
              />
              <p className="text-[9px] text-muted-foreground mt-1">Earth Engine Compute Units (EEC) quota</p>
            </div>
            <div className="col-span-2">
              <label className="text-[11px] font-medium block mb-1">Service Account API Key</label>
              <div className="relative">
                <input
                  type={showGeeKey ? "text" : "password"}
                  value={geeApiKey}
                  onChange={e => setGeeApiKey(e.target.value)}
                  className="w-full border border-border rounded-lg px-3 py-2 pr-10 text-[11px] bg-background focus:outline-none focus:border-[#166534] font-mono"
                />
                <button
                  onClick={() => setShowGeeKey(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showGeeKey ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
              </div>
              <p className="text-[9px] text-muted-foreground mt-1">Used to authenticate SAR imagery requests for crop area analysis within farm polygons.</p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3 p-2.5 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200">
            <Server size={12} className="text-blue-600 shrink-0" />
            <p className="text-[10px] text-blue-700">Connection status: <span className="font-bold text-emerald-600">Active</span> — Last SAR query: 01 Nov 2024, 08:30 PHT</p>
          </div>
        </Section>

        {/* PAGASA Parser Settings */}
        <Section title="PAGASA Parser & Notification Settings" icon={<Bell size={15} />}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[11px] font-medium block mb-1">TCB Polling Interval (minutes)</label>
              <input
                type="number" min={15} max={1440} step={15}
                value={parserInterval}
                onChange={e => setParserInterval(Number(e.target.value))}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              />
              <p className="text-[9px] text-muted-foreground mt-1">How often to check the PAGASA website for new bulletins during an active typhoon (15 min minimum).</p>
            </div>
            <div>
              <label className="text-[11px] font-medium block mb-1">Alert Email Recipients</label>
              <input
                defaultValue="a.reyes@pcic.gov.ph, gis-team@pcic.gov.ph"
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              />
              <p className="text-[9px] text-muted-foreground mt-1">Comma-separated email addresses notified when a new TCB is parsed.</p>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-border">
              <div>
                <p className="text-[11px] font-medium">Email Alerts</p>
                <p className="text-[9px] text-muted-foreground">Send email when new TCB is downloaded</p>
              </div>
              <button onClick={() => setEmailAlerts(v => !v)} className={emailAlerts ? "text-[#166534]" : "text-muted-foreground"}>
                {emailAlerts ? <ToggleRight size={24} /> : <ToggleLeft size={24} />}
              </button>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-border">
              <div>
                <p className="text-[11px] font-medium">On-Screen Pop-up Alerts</p>
                <p className="text-[9px] text-muted-foreground">Show in-app notification on new bulletin</p>
              </div>
              <button className="text-[#166534]">
                <ToggleRight size={24} />
              </button>
            </div>
          </div>
        </Section>

        {/* Session & Security */}
        <Section title="Session & Security Settings" icon={<Shield size={15} />}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[11px] font-medium block mb-1">Session Timeout (minutes)</label>
              <select
                value={sessionTimeout}
                onChange={e => setSessionTimeout(Number(e.target.value))}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              >
                {[0,5,10,15,30].map(v => <option key={v} value={v}>{v === 0 ? "Disabled" : `${v} minutes`}</option>)}
              </select>
              <p className="text-[9px] text-muted-foreground mt-1">Auto-lock terminal after inactivity. Last session is retained on re-login.</p>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border border-border">
              <div>
                <p className="text-[11px] font-medium">Auto-Save Work</p>
                <p className="text-[9px] text-muted-foreground">Prevent data loss on session timeout</p>
              </div>
              <button className="text-[#166534]">
                <ToggleRight size={24} />
              </button>
            </div>
          </div>
        </Section>

        {/* Database Backup */}
        <Section title="Database Backup & Restore" icon={<Database size={15} />} defaultOpen={false}>
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
        </Section>

        {/* User Management */}
        <Section title="User Account Management" icon={<Users size={15} />} defaultOpen={false}>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[11px] text-muted-foreground">Manage system access for GIS specialists and administrators.</p>
            <button
              onClick={() => setAddingUser(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#166534] text-white text-[11px] hover:bg-[#14532d] transition-colors"
            >
              <Plus size={11} /> Add User
            </button>
          </div>
          {usersError && (
            <p className="text-[10px] text-red-600 mb-2">{usersError}</p>
          )}
          {isLoadingUsers && users.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">Loading users…</p>
          ) : users.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-4 text-center">No user accounts yet.</p>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-muted/60 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-semibold">Name</th>
                  <th className="px-3 py-2 text-left font-semibold">Role</th>
                  <th className="px-3 py-2 text-left font-semibold">Email</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.user_id} className="border-t border-border">
                    <td className="px-3 py-2.5 font-medium">{u.name}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{u.role}</td>
                    <td className="px-3 py-2.5 text-muted-foreground font-mono text-[10px]">{u.email}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${u.is_active?"bg-emerald-100 text-emerald-700":"bg-gray-100 text-gray-500"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setEditingUser(u)}
                          className="p-1 hover:bg-muted rounded text-[#1e3a5f]"
                          title="Edit"
                        >
                          <Settings size={11} />
                        </button>
                        {u.is_active && (
                          <button
                            className="p-1 hover:bg-muted rounded text-destructive"
                            title="Deactivate"
                            onClick={() => handleDeleteUser(u.user_id)}
                          >
                            <Trash2 size={11} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>

        <div className="pb-6" />
      </div>
    </div>
  );
}
