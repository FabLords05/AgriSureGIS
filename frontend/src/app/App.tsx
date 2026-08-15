import { useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import { LoginScreen } from "./components/LoginScreen";
import { Header, ModuleId } from "./components/Header";
import { MonitoringModule } from "./components/MonitoringModule";
import { SpatialAnalysisModule } from "./components/SpatialAnalysisModule";
import { AssessmentModule } from "./components/AssessmentModule";
import { CalibrationModule } from "./components/CalibrationModule";
import { UserManagementModule } from "./components/UserManagementModule";
import { DatabaseBackupModule } from "./components/DatabaseBackupModule";
import { ActivityLogModule } from "./components/ActivityLogModule";
import { AppNotification } from "./components/mockData";
import { Bulletin, getBulletins, logoutUser } from "@/lib/api";
import { useFarmsData } from "@/lib/useFarmsData";
import { CurrentUser, loadPersistedUser, persistUser, persistToken, clearPersistedUser } from "@/lib/authStorage";

const BULLETIN_POLL_MS = 60_000;

// Real mouse/keyboard/scroll interaction only -- deliberately NOT the
// existing 60s background bulletin poll (that's a fetch the app makes on
// its own, not the user doing anything; counting it would mean a tab left
// open and untouched never actually goes idle, defeating the point).
const ACTIVITY_EVENTS = ["mousemove", "keydown", "mousedown", "scroll", "touchstart"] as const;

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
  const [darkMode, setDarkMode]           = useState(false);
  const [coverageRatePerHa, setCoverageRatePerHa] = useState(25000);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [selectedBulletin, setSelectedBulletin] = useState<Bulletin | null>(null);
  const seenMaxTcbId = useRef<number | null>(null);

  // Starts fetching farm records the moment login succeeds, regardless of
  // which tab is active -- shared by MonitoringModule (needs the complete
  // dataset for its aggregate stat cards) and SpatialAnalysisModule (its
  // table/map), instead of each independently fetching its own copy.
  const farmsData = useFarmsData(!!currentUser);

  const handleLogin = (user: CurrentUser, token: string) => {
    setCurrentUser(user);
    persistUser(user);
    persistToken(token);
    setActiveModule(user.role === "System Administrator" ? "calibration" : "monitoring");
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

  // Auto-logout after the account's configured idle minutes (0 = disabled),
  // real user interaction only (see ACTIVITY_EVENTS above) -- entirely
  // client-side per Fabio's explicit direction; the session token itself
  // carries a long fixed safety-net expiry, not a sliding one tied to this
  // (see backend/app/core/security.py's module docstring).
  useEffect(() => {
    if (!currentUser || currentUser.session_timeout_minutes <= 0) return;

    const timeoutMs = currentUser.session_timeout_minutes * 60_000;
    let timer: ReturnType<typeof setTimeout>;

    const resetTimer = () => {
      clearTimeout(timer);
      timer = setTimeout(handleLogout, timeoutMs);
    };

    ACTIVITY_EVENTS.forEach(evt => window.addEventListener(evt, resetTimer));
    resetTimer();

    return () => {
      clearTimeout(timer);
      ACTIVITY_EVENTS.forEach(evt => window.removeEventListener(evt, resetTimer));
    };
  }, [currentUser?.email, currentUser?.session_timeout_minutes]);

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
          onToggleDark={() => setDarkMode(v => !v)}
          notifications={notifications}
          onClearNotification={handleClearNotification}
          currentUser={currentUser}
          onLogout={handleLogout}
        />

        {/* isAdmin gates rendering itself, not just Header's nav -- defense in
            depth so a stale/mismatched activeModule value can never render a
            Specialist tab for an Admin or vice versa. Within the admin
            branch, anything other than "users"/"backup"/"activity" falls
            back to Admin Panel rather than rendering blank, same defensive
            spirit as before there was more than one admin tab to choose
            between. */}
        <main className="flex-1 overflow-hidden">
          {currentUser.role === "System Administrator" ? (
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
                  farmsData={farmsData}
                />
              )}
              {activeModule === "spatial"     && (
                <SpatialAnalysisModule
                  darkMode={darkMode}
                  selectedBulletin={selectedBulletin}
                  farmsData={farmsData}
                />
              )}
              {activeModule === "assessment"  && (
                <AssessmentModule darkMode={darkMode} />
              )}
            </>
          )}
        </main>

        <Toaster position="bottom-right" richColors />
      </div>
    </div>
  );
}
