import { useState } from "react";
import { Toaster } from "sonner";
import { LoginScreen } from "./components/LoginScreen";
import { Header, ModuleId } from "./components/Header";
import { MonitoringModule } from "./components/MonitoringModule";
import { SpatialAnalysisModule } from "./components/SpatialAnalysisModule";
import { AssessmentModule } from "./components/AssessmentModule";
import { CalibrationModule } from "./components/CalibrationModule";
import { mockNotifications, AppNotification } from "./components/mockData";
import { Bulletin } from "@/lib/api";

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
  const [notifications, setNotifications] = useState<AppNotification[]>(mockNotifications);
  const [selectedBulletin, setSelectedBulletin] = useState<Bulletin | null>(null);

  const handleLogin = (user: CurrentUser) => {
    setCurrentUser(user);
  };

  const handleClearNotification = (id: string) => {
    setNotifications(ns => ns.filter(n => n.id !== id));
  };

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
            <AssessmentModule
              darkMode={darkMode}
              selectedBulletin={selectedBulletin}
              onSelectBulletin={setSelectedBulletin}
            />
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
