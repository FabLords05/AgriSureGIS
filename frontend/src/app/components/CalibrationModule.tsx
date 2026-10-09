import { useEffect, useState } from "react";
import {
  Settings, Shield, Save, AlertTriangle,
  ChevronDown, ChevronRight, CheckCircle2,
  Clock, ToggleRight, DollarSign, Wifi
} from "lucide-react";
import { DAMAGE_FACTORS, GrowthStage } from "./mockData";
import { getParserSettings } from "@/lib/api";

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

interface CalibrationModuleProps {
  coverageRatePerHa: number;
  onCoverageRateChange: (rate: number) => void;
}

export function CalibrationModule({ coverageRatePerHa, onCoverageRateChange }: CalibrationModuleProps) {
  const [damageFactor, setDamageFactor] = useState<Record<GrowthStage, Record<number, number>>>(
    JSON.parse(JSON.stringify(DAMAGE_FACTORS))
  );
  const [sessionTimeout, setSessionTimeout] = useState(5);
  const [savedSuccess, setSavedSuccess] = useState(false);

  // Backend API status -- real, not mock. Reuses the existing GET
  // /api/bulletins/settings call purely as a connectivity ping now that the
  // TCB polling interval it used to also surface is fixed backend-side (see
  // build_scheduler's hardcoded 15min in scheduler.py) instead of admin-
  // configurable here.
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [lastCheck, setLastCheck] = useState<string | null>(null);

  useEffect(() => {
    getParserSettings()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false))
      .finally(() => setLastCheck(new Date().toLocaleTimeString()));
  }, []);

  const handleSave = () => {
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2500);
  };

  const stages: GrowthStage[] = ["Seedling","Vegetative","Reproductive","Ripening"];
  const signals = [1,2,3];

  return (
    <div className="h-full overflow-auto bg-background p-4">
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

        <div className="pb-6" />
      </div>
    </div>
  );
}
