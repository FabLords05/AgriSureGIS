import { useEffect, useMemo, useState } from "react";
import {
  Settings, Save, AlertTriangle,
  ChevronDown, ChevronRight, CheckCircle2,
  Clock, DollarSign, Wifi, Key, Lock
} from "lucide-react";
import { toast } from "sonner";
import {
  getParserSettings, getSystemStatus, SystemStatus,
  getSystemSettings, updateCoverageRate, getPcicMatrices, PcicMatrices,
} from "@/lib/api";

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}

function Section({ title, icon, children, defaultOpen = true, badge }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-2.5 px-4 py-3 hover:bg-muted/40 transition-colors text-left"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-[#166534]">{icon}</span>
        <span className="text-sm font-semibold flex-1">{title}</span>
        {badge && (
          <span className="flex items-center gap-1 text-[10px] text-muted-foreground px-2 py-0.5 rounded-full border border-border">
            <Lock size={9} /> {badge}
          </span>
        )}
        {open ? <ChevronDown size={14} className="text-muted-foreground" /> : <ChevronRight size={14} className="text-muted-foreground" />}
      </button>
      {open && <div className="border-t border-border px-4 py-4">{children}</div>}
    </div>
  );
}

const EXPOSURE_HOURS = [6, 12, 24];

// Admin Panel (2026-10-22): every control here is now real. The coverage rate
// is persisted (tbl_system_settings) and used at upload as the default Amount
// of Cover; the PCIC matrices are the real payout tables, shown read-only.
// The old client-only Session & Security section was removed -- per-account
// timeout lives in Account Settings / User Management.
export function CalibrationModule() {
  const [coverageRate, setCoverageRate] = useState<number | null>(null);
  const [savedRate, setSavedRate] = useState<number | null>(null);
  const [rateBounds, setRateBounds] = useState<[number, number]>([1000, 100000]);
  const [isSaving, setIsSaving] = useState(false);
  const [matrices, setMatrices] = useState<PcicMatrices | null>(null);
  const [matrixError, setMatrixError] = useState<string | null>(null);

  // Backend API status -- real, not mock. Reuses the existing GET
  // /api/bulletins/settings call purely as a connectivity ping now that the
  // TCB polling interval it used to also surface is fixed backend-side (see
  // build_scheduler's hardcoded 15min in scheduler.py) instead of admin-
  // configurable here.
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [lastCheck, setLastCheck] = useState<string | null>(null);

  // Google Earth Engine connection (2026-10-12) -- read-only. The
  // prototype's editable credentials card is deliberately not reproduced:
  // the service-account key is a live private key and stays in backend/.env.
  const [gee, setGee] = useState<SystemStatus["gee"] | null>(null);
  useEffect(() => {
    getSystemStatus().then(res => setGee(res.gee ?? null)).catch(() => setGee(null));
  }, []);

  useEffect(() => {
    getParserSettings()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false))
      .finally(() => setLastCheck(new Date().toLocaleTimeString()));
  }, []);

  useEffect(() => {
    getSystemSettings()
      .then(res => {
        setCoverageRate(res.data.coverage_rate_per_ha);
        setSavedRate(res.data.coverage_rate_per_ha);
        setRateBounds([res.data.coverage_rate_min, res.data.coverage_rate_max]);
      })
      .catch(error => toast.error(error instanceof Error ? error.message : "Failed to load settings."));
    getPcicMatrices()
      .then(res => setMatrices(res.data))
      .catch(error => setMatrixError(error instanceof Error ? error.message : "Failed to load PCIC matrices."));
  }, []);

  const rateValid = coverageRate !== null && coverageRate >= rateBounds[0] && coverageRate <= rateBounds[1];
  const rateDirty = coverageRate !== null && coverageRate !== savedRate;

  const handleSave = () => {
    if (!rateValid || coverageRate === null) return;
    setIsSaving(true);
    updateCoverageRate(coverageRate)
      .then(res => {
        setSavedRate(res.data.coverage_rate_per_ha);
        setCoverageRate(res.data.coverage_rate_per_ha);
        toast.success("Settings saved successfully.");
      })
      .catch(error => toast.error(error instanceof Error ? error.message : "Failed to save settings."))
      .finally(() => setIsSaving(false));
  };

  // RECSAP rows pivoted to one row per (stage, TCWS) with 6/12/24h columns.
  const recsapRows = useMemo(() => {
    const rows = new Map<string, { stage: string; tcws: number; byHours: Record<number, number> }>();
    for (const r of matrices?.recsap ?? []) {
      const key = `${r.crop_stage_no}-${r.wind_signal_tcws}`;
      if (!rows.has(key)) rows.set(key, { stage: r.crop_stage, tcws: r.wind_signal_tcws, byHours: {} });
      rows.get(key)!.byHours[r.exposure_hours] = r.estimated_yield_loss;
    }
    return [...rows.values()];
  }, [matrices]);

  // Indemnity factors pivoted to one row per stage group, one column per
  // yield-loss bracket (in first-seen order, which follows the seed's order).
  const indemnity = useMemo(() => {
    const brackets: string[] = [];
    const groups = new Map<string, Record<string, number>>();
    for (const r of matrices?.indemnity ?? []) {
      const bracket = `>${r.yield_loss_min}–${r.yield_loss_max}`;
      if (!brackets.includes(bracket)) brackets.push(bracket);
      if (!groups.has(r.crop_stage_group)) groups.set(r.crop_stage_group, {});
      groups.get(r.crop_stage_group)![bracket] = r.indemnity_factor;
    }
    return { brackets, groups: [...groups.entries()] };
  }, [matrices]);

  return (
    <div className="h-full overflow-auto bg-background p-4">
      <div className="max-w-5xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-bold text-foreground flex items-center gap-2">
              <Settings size={18} className="text-[#166534]" /> Calibration & Settings
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">Configure system parameters and review the PCIC payout tables.</p>
          </div>
          <button
            onClick={handleSave}
            disabled={!rateDirty || !rateValid || isSaving}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] disabled:opacity-50 transition-colors"
          >
            <Save size={13} /> {isSaving ? "Saving…" : "Save All Settings"}
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

        {/* Google Earth Engine -- read-only status for SAR planted verification */}
        <Section title="Google Earth Engine" icon={<Key size={15} />}>
          <p className="text-[11px] text-muted-foreground mb-3">
            Sentinel-1 SAR imagery for verifying that affected farms were planted. Credentials are set on the
            server (<span className="font-mono">GEE_SERVICE_ACCOUNT_KEY_PATH</span> in backend/.env), not here.
          </p>
          <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[11px]">
            <span className="text-muted-foreground">Status:</span>
            <span className="flex items-center gap-1.5">
              {gee?.connected
                ? <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
                : <AlertTriangle size={12} className="text-amber-500 shrink-0" />}
              {gee == null ? "Checking…" : gee.connected ? "Connected" : gee.configured ? "Configured, not connected" : "Not configured"}
            </span>
            <span className="text-muted-foreground">Project:</span>
            <span className="font-mono">{gee?.project_id ?? "—"}</span>
            <span className="text-muted-foreground">Service account:</span>
            <span className="font-mono break-all">{gee?.service_account ?? "—"}</span>
          </div>
          {gee?.last_error && (
            <p className="text-[10px] text-amber-600 mt-3">{gee.last_error}</p>
          )}
        </Section>

        {/* Coverage Parameters */}
        <Section title="RSBSA Coverage Rate (Default Amount of Cover)" icon={<DollarSign size={15} />}>
          <p className="text-[11px] text-muted-foreground mb-4">
            Used only when an uploaded record has <strong>no Amount of Cover</strong>: AC = rate × farm area.
            Amounts of Cover in the PABS CSV always take priority. Applies to future uploads only — records already
            on file are not changed.
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
                  min={rateBounds[0]}
                  max={rateBounds[1]}
                  step={500}
                  value={coverageRate ?? ""}
                  disabled={coverageRate === null}
                  onChange={e => setCoverageRate(Number(e.target.value))}
                  className="w-full border border-border rounded-lg pl-7 pr-3 py-2.5 text-[12px] font-bold focus:outline-none focus:border-[#166534] bg-background"
                />
              </div>
              <p className={`text-[9px] mt-1 ${coverageRate !== null && !rateValid ? "text-red-600" : "text-muted-foreground"}`}>
                Between ₱{rateBounds[0].toLocaleString()} and ₱{rateBounds[1].toLocaleString()} per hectare.
              </p>
            </div>
            <div className="text-[10px] text-muted-foreground pb-7">
              Saved value: <strong className="text-[#166534]">{savedRate === null ? "—" : `₱${savedRate.toLocaleString()}/ha`}</strong>
            </div>
          </div>
          {coverageRate !== null && rateValid && (
            <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200">
              <p className="text-[11px] font-semibold text-amber-700 mb-1">Preview — default AC for a record with no Amount of Cover</p>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-[9px] text-muted-foreground">Rate per Hectare</p>
                  <p className="text-base font-black text-amber-700">₱{coverageRate.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Sample: 2.5 ha → AC</p>
                  <p className="text-base font-black text-[#166534]">₱{(2.5 * coverageRate).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Payout at IF 146 (AC/1000 × IF)</p>
                  <p className="text-base font-black text-[#1e3a5f]">₱{((2.5 * coverageRate) / 1000 * 146).toLocaleString()}</p>
                </div>
              </div>
            </div>
          )}
        </Section>

        {/* PCIC matrices -- the real payout lookup, read-only */}
        <Section title="PCIC Yield Loss Matrix (RECSAP)" icon={<Settings size={15} />} badge="Read-only">
          <p className="text-[11px] text-muted-foreground mb-3">
            Step 1 of the payout: estimated yield loss % by crop stage, TCWS signal and hours of exposure.
          </p>
          {matrixError ? (
            <p className="text-[11px] text-red-600">{matrixError}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="text-[11px] w-full">
                <thead>
                  <tr className="bg-[#166534] text-white">
                    <th className="px-3 py-2 text-left font-semibold">Crop Stage</th>
                    <th className="px-3 py-2 text-center font-semibold">TCWS</th>
                    {EXPOSURE_HOURS.map(h => <th key={h} className="px-3 py-2 text-center font-semibold">{h}h</th>)}
                  </tr>
                </thead>
                <tbody>
                  {recsapRows.map(r => (
                    <tr key={`${r.stage}-${r.tcws}`} className="border-t border-border hover:bg-muted/30">
                      <td className="px-3 py-2 font-semibold">{r.stage}</td>
                      <td className="px-3 py-2 text-center">{r.tcws}</td>
                      {EXPOSURE_HOURS.map(h => (
                        <td key={h} className="px-3 py-2 text-center">{r.byHours[h] == null ? "—" : `${r.byHours[h]}%`}</td>
                      ))}
                    </tr>
                  ))}
                  {matrices && recsapRows.length === 0 && (
                    <tr><td colSpan={5} className="px-3 py-3 text-center text-muted-foreground">No active rows.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        <Section title="PCIC Indemnity Factor Matrix" icon={<Settings size={15} />} badge="Read-only">
          <p className="text-[11px] text-muted-foreground mb-3">
            Step 2: indemnity factor (IF) by crop stage group and yield-loss bracket. Payout I = (AC / 1000) × IF.
          </p>
          {matrixError ? (
            <p className="text-[11px] text-red-600">{matrixError}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="text-[11px] w-full">
                <thead>
                  <tr className="bg-[#166534] text-white">
                    <th className="px-3 py-2 text-left font-semibold whitespace-nowrap">Stage Group</th>
                    {indemnity.brackets.map(b => <th key={b} className="px-3 py-2 text-center font-semibold whitespace-nowrap">{b}%</th>)}
                  </tr>
                </thead>
                <tbody>
                  {indemnity.groups.map(([group, values]) => (
                    <tr key={group} className="border-t border-border hover:bg-muted/30">
                      <td className="px-3 py-2 font-semibold whitespace-nowrap">{group}</td>
                      {indemnity.brackets.map(b => (
                        <td key={b} className="px-3 py-2 text-center">{values[b] ?? "—"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-[10px] text-muted-foreground mt-2">
            Source: PCIC Rice Indemnity Factor Table. Changed only by database migration, so payouts stay matched to official PCIC forms.
          </p>
        </Section>

        <div className="pb-6" />
      </div>
    </div>
  );
}
