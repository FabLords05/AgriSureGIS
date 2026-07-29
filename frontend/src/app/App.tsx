import { useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import { LoginScreen } from "./components/LoginScreen";
import { Header, ModuleId } from "./components/Header";
import { MonitoringModule } from "./components/MonitoringModule";
import { SpatialAnalysisModule } from "./components/SpatialAnalysisModule";
import { AssessmentModule } from "./components/AssessmentModule";
import { CalibrationModule } from "./components/CalibrationModule";
import { AppNotification } from "./components/mockData";
import { Bulletin, getBulletins } from "@/lib/api";

const BULLETIN_POLL_MS = 60_000;

interface CurrentUser {
  name: string;
  role: string;
  email: string;
}

export default function App() {
  const [currentUser, setCurrentUser]     = useState<CurrentUser | null>(null);
  const [activeModule, setActiveModule]   = useState<ModuleId>("monitoring");
  const [darkMode, setDarkMode]           = useState(false);
  const [coverageRatePerHa, setCoverageRatePerHa] = useState(25000);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [selectedBulletin, setSelectedBulletin] = useState<Bulletin | null>(null);
  const seenMaxTcbId = useRef<number | null>(null);

  const handleLogin = (user: CurrentUser) => {
    setCurrentUser(user);
  };

  const handleClearNotification = (id: string) => {
    setNotifications(ns => ns.filter(n => n.id !== id));
  };

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
          onLogout={() => setCurrentUser(null)}
        />

        <main className="flex-1 overflow-hidden">
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
            />
          )}
          {activeModule === "assessment"  && (
            <AssessmentModule darkMode={darkMode} />
          )}
          {activeModule === "calibration" && (
            <CalibrationModule
              coverageRatePerHa={coverageRatePerHa}
              onCoverageRateChange={setCoverageRatePerHa}
            />
          )}
        </main>

        <Toaster position="bottom-right" richColors />
      </div>
    </div>
  );
}
