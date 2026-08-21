import { useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import { AlertCircle, X } from "lucide-react";
import { LoginScreen } from "./components/LoginScreen";
import { LoggedOutNotice, LogoutReason } from "./components/LoggedOutNotice";
import { Header, ModuleId } from "./components/Header";
import { MonitoringModule } from "./components/MonitoringModule";
import { SpatialAnalysisModule } from "./components/SpatialAnalysisModule";
import { AssessmentModule } from "./components/AssessmentModule";
import { CalibrationModule } from "./components/CalibrationModule";
import { UserManagementModule } from "./components/UserManagementModule";
import { DatabaseBackupModule } from "./components/DatabaseBackupModule";
import { ActivityLogModule } from "./components/ActivityLogModule";
import { AccountSettingsModule } from "./components/AccountSettingsModule";
import { AppNotification } from "./components/mockData";
import {
  Bulletin, getBulletins, logoutUser, SystemUser,
  uploadCsv, uploadGpx, getCsvUploadStatus,
} from "@/lib/api";
import { useFarmsData } from "@/lib/useFarmsData";
import { CurrentUser, loadPersistedUser, persistUser, persistToken, clearPersistedUser } from "@/lib/authStorage";
import { loadPersistedDarkMode, persistDarkMode } from "@/lib/themeStorage";
import { loadPersistedHeaderHideMode, persistHeaderHideMode, HeaderHideMode } from "@/lib/headerHideModeStorage";
import { SESSION_EXPIRED_EVENT } from "@/lib/sessionEvents";

const BULLETIN_POLL_MS = 60_000;

// Real mouse/keyboard/scroll interaction only -- deliberately NOT the
// existing 60s background bulletin poll (that's a fetch the app makes on
// its own, not the user doing anything; counting it would mean a tab left
// open and untouched never actually goes idle, defeating the point).
const ACTIVITY_EVENTS = ["mousemove", "keydown", "mousedown", "scroll", "touchstart"] as const;

// Polls the backend CSV job every 500ms for real processed/total counts (see
// getCsvUploadStatus) -- not a simulated/fake bar. 500ms is frequent enough
// to feel live without hammering the backend on every tick of a large export
// that can take a while.
const CSV_POLL_MS = 500;

// ─── Upload Failures Modal ───────────────────────────────────────────────────
// A batch GPX upload can produce dozens of per-file failures -- these used to
// get joined into one giant string and dumped straight into the status
// banner with no size limit, which could balloon to the point of visually
// swallowing the whole page (reported by Fabio). Each failure is now its own
// row in a scrollable, height-capped panel instead. Rendered at the App root
// (2026-08-20, moved out of SpatialAnalysisModule alongside the upload
// handlers below) so "View details" on the toast still works even if the
// user has since switched away from the Spatial tab.
function UploadFailuresModal({ failures, onClose }: { failures: string[]; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-[560px] max-h-[70vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0" style={{ background: "#0f1e0f" }}>
          <div className="flex items-center gap-2.5">
            <AlertCircle size={15} className="text-red-400" />
            <p className="text-[12px] font-bold text-white">{failures.length} file(s) failed to upload</p>
          </div>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors">
            <X size={13} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          <ul className="space-y-1.5">
            {failures.map((f, i) => (
              <li key={i} className="text-[11px] px-3 py-2 rounded-lg bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border border-red-100 dark:border-red-900">
                {f}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-end px-5 py-3 border-t border-border shrink-0">
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-border text-xs hover:bg-muted transition-colors">Close</button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  // Lazy initializer reads localStorage synchronously on first render, so a
  // refresh never flashes the login screen before rehydrating -- the user
  // stays logged in until they explicitly log out (see handleLogout below).
  const [currentUser, setCurrentUser]     = useState<CurrentUser | null>(loadPersistedUser);
  // System Administrators only ever see the Calibration/Admin panel (see
  // Header.tsx's ADMIN_MODULES) -- default there directly instead of
  // "monitoring", which isn't even a navigable tab for that role. Covers
  // both a fresh admin login and a page refresh rehydrating a persisted
  // admin session.
  const [activeModule, setActiveModule]   = useState<ModuleId>(
    () => loadPersistedUser()?.role === "System Administrator" ? "calibration" : "monitoring"
  );
  // Lazy initializer, same reasoning as currentUser above -- reads
  // localStorage synchronously so a refresh never flashes light mode before
  // rehydrating the user's last choice. Keyed by the persisted user's email
  // (themeStorage.ts) so this is *that user's* preference, not whichever
  // user last set it on this browser -- falls back to light mode when
  // there's no persisted user yet (fresh login screen, nobody to key by).
  const [darkMode, setDarkMode]           = useState(() => {
    const user = loadPersistedUser();
    return user ? loadPersistedDarkMode(user.email) : false;
  });
  // Same lazy-init/per-user pattern as darkMode above, for the header's
  // hide-mode preference (2026-08-18, set from Account Settings' "Display
  // Preferences" card -- see AccountSettingsModule.tsx and Header.tsx).
  const [headerHideMode, setHeaderHideModeState] = useState<HeaderHideMode>(() => {
    const user = loadPersistedUser();
    return user ? loadPersistedHeaderHideMode(user.email) : "manual";
  });
  // Persists alongside updating state, same shape as onToggleDark below --
  // passed to AccountSettingsModule so picking a new mode there applies
  // immediately (no Save button; this is client-only, not part of
  // SystemUser/updateMe()) and survives a refresh for this user.
  const handleHeaderHideModeChange = (mode: HeaderHideMode) => {
    setHeaderHideModeState(mode);
    if (currentUser) persistHeaderHideMode(currentUser.email, mode);
  };
  // Set only for *involuntary* logout (idle timeout / expired session token)
  // -- see the two effects below. null means either "still logged in" or
  // "logged out on purpose" (the Header's Sign Out button calls handleLogout
  // directly and never touches this), in which case render falls straight
  // through to LoginScreen as before. Non-null renders LoggedOutNotice
  // instead, and only clears back to null (reaching LoginScreen) once the
  // user clicks through it.
  const [logoutReason, setLogoutReason]   = useState<LogoutReason | null>(null);
  const [coverageRatePerHa, setCoverageRatePerHa] = useState(25000);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [selectedBulletin, setSelectedBulletin] = useState<Bulletin | null>(null);
  const seenMaxTcbId = useRef<number | null>(null);

  // CSV/GPX upload progress + the failure-details modal that backs it --
  // owned here (not in SpatialAnalysisModule) for the same reason farmsData
  // is owned here: that module is conditionally mounted (only while
  // activeModule === "spatial"), so a local-state polling loop would freeze
  // -- and its completion toast could be missed entirely -- the moment the
  // user switched to another module tab before the upload finished
  // (2026-08-20, per Fabio: "there is no way to tell user is it done or
  // not"). null = no upload in flight.
  const [csvUploadProgress, setCsvUploadProgress] = useState<{ processed: number; total: number } | null>(null);
  const [gpxUploadProgress, setGpxUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const [uploadFailureDetails, setUploadFailureDetails] = useState<string[] | null>(null);
  const [showUploadDetails, setShowUploadDetails] = useState(false);

  // SpatialAnalysisModule's Farm Records table/map filters -- owned here
  // (not locally in that module) because useFarmsData is owned here too:
  // SpatialAnalysisModule is conditionally mounted (only while
  // activeModule === "spatial"), so keeping the hook + its filter state at
  // this level means switching tabs away and back doesn't drop progress or
  // re-fetch from scratch. Default (`filterMuni === "All"`, i.e.
  // municipality: null, and no farmer picked) fetches active-insurance
  // farms across every municipality, same default view as before the
  // on-demand-pagination redesign (2026-08-18, stage 2 --
  // .claude/FUNCTION_CHANGES.md) -- small and safe, bounded by however many
  // farms actually have active insurance. Only "every farm, active or not,
  // no municipality or farmer scope" is unbounded at 100k-1M scale (see
  // useFarmsData.ts's module docstring), so that's the one combination the
  // hook refuses to fetch for. `filterFarmerId` (2026-08-18, farmer
  // search) scopes exactly like `filterMuni` -- either one alone is enough
  // to allow Active Insurance Only to be turned off. The search box's own
  // typed text/suggestions stay local to SpatialAnalysisModule (same
  // pattern as muniQuery) -- only the committed farmer_id lives here.
  const [activeInsuranceOnly, setActiveInsuranceOnly] = useState(true);
  const [filterMuni, setFilterMuni] = useState("All");
  const [filterFarmerId, setFilterFarmerId] = useState<number | null>(null);
  // Guards against landing in the unbounded combination: if the user had
  // turned Active Insurance Only off while a municipality or farmer was
  // selected, then clears both back to "nothing selected", this forces it
  // back on rather than leaving the table/map stuck showing nothing.
  useEffect(() => {
    if (filterMuni === "All" && filterFarmerId == null && !activeInsuranceOnly) {
      setActiveInsuranceOnly(true);
    }
  }, [filterMuni, filterFarmerId, activeInsuranceOnly]);
  const farmsData = useFarmsData({
    enabled: !!currentUser,
    activeOnly: activeInsuranceOnly,
    municipality: filterMuni === "All" ? null : filterMuni,
    farmerId: filterFarmerId,
  });

  const handleLogin = (user: CurrentUser, token: string) => {
    setCurrentUser(user);
    persistUser(user);
    persistToken(token);
    setActiveModule(user.role === "System Administrator" ? "calibration" : "monitoring");
    // Switch to *this* user's own dark-mode/header-hide-mode preferences --
    // otherwise a shared device would keep showing whichever settings the
    // previous user left it in until this user happens to change them.
    setDarkMode(loadPersistedDarkMode(user.email));
    setHeaderHideModeState(loadPersistedHeaderHideMode(user.email));
  };

  // Account Settings tab hands back the full updated row after a save --
  // reconcile it into currentUser/localStorage immediately (no re-login
  // needed) so the idle-timeout effect below picks up a changed session
  // timeout right away, and the Header user menu reflects a changed
  // name/email without a refresh.
  const handleAccountUpdate = (updated: SystemUser) => {
    const next: CurrentUser = {
      name: updated.name,
      role: updated.role,
      email: updated.email,
      session_timeout_minutes: updated.session_timeout_minutes,
    };
    setCurrentUser(next);
    persistUser(next);
  };

  const handleLogout = () => {
    // Fire-and-forget -- records the LOGOUT activity-log entry, but logging
    // out must never be blocked/delayed by a slow or failed network call.
    // Must run before clearPersistedUser() below, while the token this call
    // authenticates with is still in storage.
    logoutUser().catch(() => {});
    setCurrentUser(null);
    clearPersistedUser();
  };

  const handleClearNotification = (id: string) => {
    setNotifications(ns => ns.filter(n => n.id !== id));
  };

  // Same shape/logic as before this was lifted out of SpatialAnalysisModule
  // (see its doc comment above) -- the only change is that success/error
  // also lands a durable entry in the notification bell (same pattern
  // bulletin parses already use, see the poll effect below), not just a
  // toast that's gone the moment it fades.
  const handleCsvFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same filename later
    if (!file) return;

    try {
      const { job_id, total_rows } = await uploadCsv(file);
      setCsvUploadProgress({ processed: 0, total: total_rows });

      // eslint-disable-next-line no-constant-condition
      while (true) {
        await new Promise(resolve => setTimeout(resolve, CSV_POLL_MS));
        const status = await getCsvUploadStatus(job_id);
        setCsvUploadProgress({ processed: status.processed, total: status.total });

        if (status.status === "done" && status.result) {
          const result = status.result;
          const failedSuffix = result.rows_failed > 0 ? `, ${result.rows_failed} failed` : "";
          const message = `${result.message} (${result.rows_inserted} inserted, ${result.rows_skipped} skipped${failedSuffix})`;
          toast.success(message);
          setNotifications(ns => [{
            id: `csv-upload-${job_id}`,
            type: result.rows_failed > 0 ? "warning" : "success",
            title: "CSV Import Finished",
            message,
            timestamp: new Date().toLocaleTimeString("en-PH", { hour: "2-digit", minute: "2-digit" }) + " PHT",
            read: false,
          }, ...ns]);
          farmsData.refresh();
          break;
        }
        if (status.status === "error") {
          const message = status.error ?? "CSV upload failed.";
          toast.error(message);
          setNotifications(ns => [{
            id: `csv-upload-${job_id}`,
            type: "warning",
            title: "CSV Import Failed",
            message,
            timestamp: new Date().toLocaleTimeString("en-PH", { hour: "2-digit", minute: "2-digit" }) + " PHT",
            read: false,
          }, ...ns]);
          break;
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "CSV upload failed.";
      toast.error(message);
      setNotifications(ns => [{
        id: `csv-upload-${Date.now()}`,
        type: "warning",
        title: "CSV Import Failed",
        message,
        timestamp: new Date().toLocaleTimeString("en-PH", { hour: "2-digit", minute: "2-digit" }) + " PHT",
        read: false,
      }, ...ns]);
    } finally {
      setCsvUploadProgress(null);
    }
  };

  // Farmer/farm for each file is auto-detected from its filename (see
  // GpxFarmerMatcherService) -- uploaded one at a time, not in parallel, so a
  // large batch doesn't hammer the backend all at once. Each file completing
  // is itself the progress signal (no backend job needed, unlike CSV above).
  const handleGpxFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-selecting the same filename(s) later
    if (files.length === 0) return;

    let succeeded = 0;
    const failures: string[] = [];
    setGpxUploadProgress({ current: 0, total: files.length });
    try {
      for (const [index, file] of files.entries()) {
        try {
          await uploadGpx(file);
          succeeded++;
        } catch (error) {
          failures.push(`${file.name}: ${error instanceof Error ? error.message : "upload failed"}`);
        }
        setGpxUploadProgress({ current: index + 1, total: files.length });
      }

      const timestamp = new Date().toLocaleTimeString("en-PH", { hour: "2-digit", minute: "2-digit" }) + " PHT";
      if (failures.length === 0) {
        const message = `Uploaded ${succeeded} GPX file(s) successfully.`;
        toast.success(message);
        setNotifications(ns => [{
          id: `gpx-upload-${Date.now()}`,
          type: "success",
          title: "GPX Import Finished",
          message,
          timestamp,
          read: false,
        }, ...ns]);
      } else {
        const message = `${succeeded} succeeded, ${failures.length} failed.`;
        toast.error(message, {
          action: {
            label: "View details",
            onClick: () => { setUploadFailureDetails(failures); setShowUploadDetails(true); },
          },
        });
        setNotifications(ns => [{
          id: `gpx-upload-${Date.now()}`,
          type: "warning",
          title: "GPX Import Finished",
          message,
          timestamp,
          read: false,
        }, ...ns]);
      }
      farmsData.refresh();
    } finally {
      setGpxUploadProgress(null);
    }
  };

  // Auto-logout after the account's configured idle minutes (0 = disabled),
  // real user interaction only (see ACTIVITY_EVENTS above) -- entirely
  // client-side per Fabio's explicit direction; the session token itself
  // carries a long fixed safety-net expiry, not a sliding one tied to this
  // (see backend/app/core/security.py's module docstring). Unlike a manual
  // Sign Out, this also flags logoutReason so the user sees why they landed
  // back at login (see LoggedOutNotice.tsx) instead of it just happening.
  useEffect(() => {
    if (!currentUser || currentUser.session_timeout_minutes <= 0) return;

    const timeoutMs = currentUser.session_timeout_minutes * 60_000;
    let timer: ReturnType<typeof setTimeout>;

    const resetTimer = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        handleLogout();
        setLogoutReason("idle");
      }, timeoutMs);
    };

    ACTIVITY_EVENTS.forEach(evt => window.addEventListener(evt, resetTimer));
    resetTimer();

    return () => {
      clearTimeout(timer);
      ACTIVITY_EVENTS.forEach(evt => window.removeEventListener(evt, resetTimer));
    };
  }, [currentUser?.email, currentUser?.session_timeout_minutes]);

  // api.ts dispatches this the moment any request comes back 401 (token
  // missing/expired/account deactivated) -- it already force-cleared
  // localStorage itself (see its request() comment) since that has to
  // happen synchronously regardless of whether React is still mounted to
  // hear about it; this just clears the in-memory user and shows the same
  // involuntary-logout notice as the idle-timeout path above.
  useEffect(() => {
    const onSessionExpired = () => {
      setCurrentUser(null);
      setLogoutReason("expired");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
  }, []);

  // Polls for bulletins the background PAGASA scheduler parsed on its own (no
  // manual "Parse Latest Bulletin" click involved) and surfaces them as an
  // in-app toast + notification-bell entry. First poll after login only sets
  // the baseline — it must not re-notify about bulletins that already existed.
  useEffect(() => {
    if (!currentUser) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const bulletins = await getBulletins();
        if (cancelled || bulletins.length === 0) return;
        const maxId = Math.max(...bulletins.map(b => b.tcb_id));

        if (seenMaxTcbId.current === null) {
          seenMaxTcbId.current = maxId;
          return;
        }
        if (maxId > seenMaxTcbId.current) {
          const newest = bulletins.find(b => b.tcb_id === maxId)!;
          seenMaxTcbId.current = maxId;
          const notif: AppNotification = {
            id: `bulletin-${newest.tcb_id}`,
            type: "bulletin",
            title: "New TCB Parsed",
            message: `Bulletin No. ${newest.bulletin_count} for ${newest.typhoon_name} has been downloaded and parsed successfully.`,
            timestamp: new Date().toLocaleTimeString("en-PH", { hour: "2-digit", minute: "2-digit" }) + " PHT",
            read: false,
          };
          setNotifications(ns => [notif, ...ns]);
          toast.success(notif.title, { description: notif.message });
        }
      } catch {
        // Silent — a failed poll shouldn't surface as a user-facing error.
      }
    };

    poll();
    const id = setInterval(poll, BULLETIN_POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [currentUser]);

  // Checked ahead of the currentUser check below -- both involuntary-logout
  // paths above already clear currentUser, so without this the app would
  // fall straight through to LoginScreen and the user would never see why.
  if (logoutReason) {
    return (
      <div className={darkMode ? "dark" : ""}>
        <LoggedOutNotice reason={logoutReason} onAcknowledge={() => setLogoutReason(null)} />
        <Toaster position="bottom-right" richColors />
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div className={darkMode ? "dark" : ""}>
        <LoginScreen onLogin={handleLogin} />
        <Toaster position="bottom-right" richColors />
      </div>
    );
  }

  return (
    <div className={darkMode ? "dark" : ""}>
      <div className="flex flex-col bg-background text-foreground" style={{ height: "100vh", overflow: "hidden" }}>
        <Header
          activeModule={activeModule}
          onModuleChange={setActiveModule}
          darkMode={darkMode}
          onToggleDark={() => setDarkMode(v => {
            const next = !v;
            if (currentUser) persistDarkMode(currentUser.email, next);
            return next;
          })}
          notifications={notifications}
          onClearNotification={handleClearNotification}
          currentUser={currentUser}
          onLogout={handleLogout}
          hideMode={headerHideMode}
        />

        {/* isAdmin gates rendering itself, not just Header's nav -- defense in
            depth so a stale/mismatched activeModule value can never render a
            Specialist tab for an Admin or vice versa. Within the admin
            branch, anything other than "users"/"backup"/"activity" falls
            back to Admin Panel rather than rendering blank, same defensive
            spirit as before there was more than one admin tab to choose
            between. Account Settings (2026-08-16) is checked first since,
            unlike every other tab, it's available to both roles alike. */}
        <main className="flex-1 overflow-hidden">
          {activeModule === "account" ? (
            <AccountSettingsModule
              currentUser={currentUser}
              onUpdated={handleAccountUpdate}
              headerHideMode={headerHideMode}
              onHeaderHideModeChange={handleHeaderHideModeChange}
            />
          ) : currentUser.role === "System Administrator" ? (
            activeModule === "users" ? (
              <UserManagementModule />
            ) : activeModule === "backup" ? (
              <DatabaseBackupModule />
            ) : activeModule === "activity" ? (
              <ActivityLogModule />
            ) : (
              <CalibrationModule
                coverageRatePerHa={coverageRatePerHa}
                onCoverageRateChange={setCoverageRatePerHa}
              />
            )
          ) : (
            <>
              {activeModule === "monitoring"  && (
                <MonitoringModule
                  darkMode={darkMode}
                  selectedBulletin={selectedBulletin}
                  onSelectBulletin={setSelectedBulletin}
                />
              )}
              {activeModule === "spatial"     && (
                <SpatialAnalysisModule
                  darkMode={darkMode}
                  selectedBulletin={selectedBulletin}
                  farmsData={farmsData}
                  activeInsuranceOnly={activeInsuranceOnly}
                  onActiveInsuranceOnlyChange={setActiveInsuranceOnly}
                  filterMuni={filterMuni}
                  onFilterMuniChange={setFilterMuni}
                  filterFarmerId={filterFarmerId}
                  onFilterFarmerIdChange={setFilterFarmerId}
                  csvUploadProgress={csvUploadProgress}
                  gpxUploadProgress={gpxUploadProgress}
                  onCsvFileSelected={handleCsvFileSelected}
                  onGpxFilesSelected={handleGpxFilesSelected}
                />
              )}
              {activeModule === "assessment"  && (
                <AssessmentModule darkMode={darkMode} />
              )}
            </>
          )}
        </main>

        {showUploadDetails && uploadFailureDetails && (
          <UploadFailuresModal failures={uploadFailureDetails} onClose={() => setShowUploadDetails(false)} />
        )}
        <Toaster position="bottom-right" richColors />
      </div>
    </div>
  );
}
