import { useState } from "react";
import {
  Home, Map, FileText, Settings, Bell, Moon, Sun, ChevronDown, ChevronUp,
  User, LogOut, Shield, RefreshCw, CheckCircle2, Users, Database, Activity, UserCog
} from "lucide-react";
import { AppNotification } from "./mockData";

export type ModuleId = "monitoring" | "spatial" | "assessment" | "calibration" | "users" | "backup" | "activity" | "account";

interface HeaderProps {
  activeModule: ModuleId;
  onModuleChange: (m: ModuleId) => void;
  darkMode: boolean;
  onToggleDark: () => void;
  notifications: AppNotification[];
  onClearNotification: (id: string) => void;
  currentUser?: { name: string; role: string; email: string };
  onLogout?: () => void;
}

const SPECIALIST_MODULES: { id: ModuleId; label: string; icon: React.ReactNode; shortLabel: string }[] = [
  { id:"monitoring",   label:"Monitoring & Extraction",        shortLabel:"Monitoring",    icon:<Home size={15} /> },
  { id:"spatial",      label:"Spatial Analysis & Data Import", shortLabel:"Spatial",       icon:<Map size={15} /> },
  { id:"assessment",   label:"Assessment & Reporting",         shortLabel:"Assessment",    icon:<FileText size={15} /> },
];

// System Administrators get their own dedicated tabs (Admin Panel / User
// Management / Database Backup / Activity Log) instead of the 3 specialist-
// facing tabs -- per Fabio's explicit request to keep admin focused on
// admin privileges/maintenance, not the regular GIS workflow. User
// Management and Database Backup used to be nested sections inside Admin
// Panel; split into their own tabs so neither is buried behind an
// accordion. Activity Log is new (2026-08-16).
const ADMIN_MODULES: { id: ModuleId; label: string; icon: React.ReactNode; shortLabel: string }[] = [
  { id:"calibration",  label:"Admin Panel",                    shortLabel:"Admin",         icon:<Settings size={15} /> },
  { id:"users",        label:"User Management",                shortLabel:"Users",         icon:<Users size={15} /> },
  { id:"backup",       label:"Database Backup",                shortLabel:"Backup",        icon:<Database size={15} /> },
  { id:"activity",     label:"Activity Log",                   shortLabel:"Activity",      icon:<Activity size={15} /> },
];

// Personal account settings (2026-08-16) -- unlike the role-specific lists
// above, every user gets this tab regardless of Specialist/Admin, so it's
// appended separately rather than duplicated into both arrays.
const ACCOUNT_MODULE: { id: ModuleId; label: string; icon: React.ReactNode; shortLabel: string } =
  { id:"account", label:"Account Settings", shortLabel:"Account", icon:<UserCog size={15} /> };

export function Header({ activeModule, onModuleChange, darkMode, onToggleDark, notifications, onClearNotification, currentUser, onLogout }: HeaderProps) {
  const [showNotifs, setShowNotifs] = useState(false);
  const [showUser, setShowUser] = useState(false);
  // Collapsible header (2026-08-18, per Fabio's request -- "like on Word,
  // that it can be hide") -- same idea as Word's ribbon-collapse toggle:
  // collapsed hides the whole header (logo, tabs, every control) down to a
  // thin strip with just the button to bring it back. Deliberately
  // component-local, non-persisted state -- a per-session convenience, not
  // a saved preference like darkMode.
  const [collapsed, setCollapsed] = useState(false);
  const isAdmin = currentUser?.role === "System Administrator";
  const modules = [...(isAdmin ? ADMIN_MODULES : SPECIALIST_MODULES), ACCOUNT_MODULE];
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshDone, setRefreshDone] = useState(false);
  const unread = notifications.filter(n => !n.read).length;

  const handleRefresh = () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setTimeout(() => {
      setIsRefreshing(false);
      setRefreshDone(true);
      setTimeout(() => setRefreshDone(false), 2000);
    }, 1500);
  };

  const notifTypeColors: Record<string, string> = {
    bulletin: "bg-blue-500",
    warning:  "bg-amber-500",
    info:     "bg-[#166534]",
    success:  "bg-emerald-500",
  };

  if (collapsed) {
    return (
      <div
        onClick={() => setCollapsed(false)}
        className="h-5 flex items-center justify-center shrink-0 cursor-pointer select-none group z-50"
        style={{ background: darkMode ? "#0f1e0f" : "#166534" }}
        title="Show menu"
      >
        <ChevronDown size={13} className="text-white/50 group-hover:text-white transition-colors" />
      </div>
    );
  }

  return (
    <header
      className="h-14 flex items-center px-0 z-50 shrink-0 select-none"
      style={{ background: darkMode ? "#0f1e0f" : "#166534" }}
    >
      {/* Logo / Brand */}
      <div className="flex items-center gap-2.5 px-4 h-full border-r border-white/15 min-w-[200px]">
        <div className="w-8 h-8 rounded-lg bg-white/15 flex items-center justify-center shrink-0">
          <span className="text-white font-black text-sm">P</span>
        </div>
        <div>
          <p className="text-white text-[11px] font-bold leading-tight tracking-wide">PCIC-GIS</p>
          <p className="text-white/60 text-[9px] leading-tight">Risk Assessment System</p>
        </div>
      </div>

      {/* Module Tabs */}
      <nav className="flex items-center h-full flex-1 px-1">
        {modules.map(m => (
          <button
            key={m.id}
            onClick={() => onModuleChange(m.id)}
            className="relative h-full flex items-center gap-1.5 px-4 text-[12px] transition-all"
            style={{
              color: activeModule === m.id ? "#ffffff" : "rgba(255,255,255,0.65)",
              background: activeModule === m.id ? "rgba(255,255,255,0.12)" : "transparent",
            }}
          >
            {m.icon}
            <span className="hidden xl:inline">{m.label}</span>
            <span className="xl:hidden">{m.shortLabel}</span>
            {activeModule === m.id && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t"
                style={{ background: "#fbbf24" }}
              />
            )}
          </button>
        ))}
      </nav>

      {/* Right Controls */}
      <div className="flex items-center gap-1 px-3 h-full">
        {/* PAGASA status pill */}
        <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/10 border border-white/15">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-white/80 text-[10px]">Parser Active</span>
        </div>

        {/* Refresh */}
        <button
          onClick={handleRefresh}
          className="w-8 h-8 rounded flex items-center justify-center hover:bg-white/10 transition-colors"
          title="Refresh parser status"
        >
          {refreshDone
            ? <CheckCircle2 size={14} className="text-emerald-300" />
            : <RefreshCw size={14} className={isRefreshing ? "text-white animate-spin" : "text-white/70"} />
          }
        </button>

        {/* Dark mode toggle */}
        <button
          onClick={onToggleDark}
          className="w-8 h-8 rounded flex items-center justify-center hover:bg-white/10 transition-colors"
          title={darkMode ? "Light Mode" : "Dark Mode"}
        >
          {darkMode ? <Sun size={14} className="text-amber-300" /> : <Moon size={14} className="text-white/70" />}
        </button>

        {/* Notification Bell */}
        <div className="relative">
          <button
            onClick={() => { setShowNotifs(v => !v); setShowUser(false); }}
            className="w-8 h-8 rounded flex items-center justify-center hover:bg-white/10 transition-colors relative"
          >
            <Bell size={14} className="text-white/70" />
            {unread > 0 && (
              <span className="absolute top-1 right-1 w-3.5 h-3.5 rounded-full bg-amber-400 text-[8px] text-black font-bold flex items-center justify-center">
                {unread}
              </span>
            )}
          </button>

          {showNotifs && (
            <div className="absolute right-0 top-full mt-1 w-80 bg-card border border-border rounded-xl shadow-2xl z-50 overflow-hidden">
              <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                <span className="text-xs font-semibold">Notifications</span>
                <span className="text-[10px] text-muted-foreground">{unread} unread</span>
              </div>
              <div className="max-h-72 overflow-y-auto">
                {notifications.map(n => (
                  <div
                    key={n.id}
                    className={`flex gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0 hover:bg-muted/50 ${!n.read ? "bg-muted/30" : ""}`}
                  >
                    <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${notifTypeColors[n.type]}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] font-semibold">{n.title}</p>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">{n.message}</p>
                      <p className="text-[9px] text-muted-foreground mt-0.5">{n.timestamp}</p>
                    </div>
                    <button
                      onClick={() => onClearNotification(n.id)}
                      className="text-[10px] text-muted-foreground hover:text-foreground shrink-0"
                    >✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* User Menu */}
        <div className="relative">
          <button
            onClick={() => { setShowUser(v => !v); setShowNotifs(false); }}
            className="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-white/10 transition-colors"
          >
            <div className="w-6 h-6 rounded-full bg-white/20 flex items-center justify-center">
              <User size={11} className="text-white" />
            </div>
            <span className="text-white/80 text-[11px] hidden md:inline">
              {currentUser ? currentUser.name.split(" ")[0] + " " + currentUser.name.split(" ").pop() : "GIS Specialist"}
            </span>
            <ChevronDown size={11} className="text-white/60" />
          </button>

          {showUser && (
            <div className="absolute right-0 top-full mt-1 w-52 bg-card border border-border rounded-xl shadow-2xl z-50 overflow-hidden">
              <div className="px-3 py-2.5 border-b border-border">
                <p className="text-xs font-semibold">{currentUser?.name ?? "Unknown User"}</p>
                <p className="text-[10px] text-muted-foreground">{currentUser?.role ?? "GIS Specialist"}</p>
                <p className="text-[10px] text-muted-foreground font-mono">{currentUser?.email ?? ""}</p>
              </div>
              <div className="py-1">
                {isAdmin && (
                  <button
                    onClick={() => { setShowUser(false); onModuleChange("calibration"); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-[11px] hover:bg-muted transition-colors"
                  >
                    <Shield size={12} /> Admin Panel
                  </button>
                )}
                <button
                  onClick={() => { setShowUser(false); onLogout?.(); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[11px] hover:bg-muted transition-colors text-destructive"
                >
                  <LogOut size={12} /> Sign Out
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Collapse header -- see the `collapsed` state above */}
        <button
          onClick={() => setCollapsed(true)}
          className="w-8 h-8 rounded flex items-center justify-center hover:bg-white/10 transition-colors"
          title="Hide menu"
        >
          <ChevronUp size={14} className="text-white/70" />
        </button>
      </div>
    </header>
  );
}
