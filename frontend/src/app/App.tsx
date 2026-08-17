import { useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
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
import { Bulletin, getBulletins, logoutUser, SystemUser } from "@/lib/api";
import { useFarmsData } from "@/lib/useFarmsData";
import { CurrentUser, loadPersistedUser, persistUser, persistToken, clearPersistedUser } from "@/lib/authStorage";
import { loadPersistedDarkMode, persistDarkMode } from "@/lib/themeStorage";
import { SESSION_EXPIRED_EVENT } from "@/lib/sessionEvents";

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
    // Switch to *this* user's own dark-mode preference -- otherwise a
    // shared device would keep showing whichever mode the previous user
    // left it in until this user happens to toggle it themselves.
    setDarkMode(loadPersistedDarkMode(user.email));
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
            <AccountSettingsModule currentUser={currentUser} onUpdated={handleAccountUpdate} />
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
