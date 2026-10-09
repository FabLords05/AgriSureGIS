import { useState } from "react";
import { UserCog, Save, KeyRound } from "lucide-react";
import { updateMe, SystemUser } from "@/lib/api";
import { CurrentUser } from "@/lib/authStorage";
import { HeaderHideMode } from "@/lib/headerHideModeStorage";

// New self-service tab (2026-08-16) -- every role gets this (see Header.tsx's
// ACCOUNT_MODULE), unlike UserManagementModule.tsx which is the admin-only
// screen for editing *other* accounts. Deliberately can't touch role/active
// status on yourself -- backend/app/api/users.py's update_me() has no
// payload shape for that at all.

interface AccountSettingsModuleProps {
  currentUser: CurrentUser;
  onUpdated: (user: SystemUser) => void;
  // Header hide-mode preference (2026-08-18) -- unlike everything else on
  // this screen, this is client-only (localStorage, see
  // headerHideModeStorage.ts), not part of SystemUser/updateMe(), so it's
  // a controlled pair from App.tsx rather than local state + a Save button.
  headerHideMode: HeaderHideMode;
  onHeaderHideModeChange: (mode: HeaderHideMode) => void;
}

const SESSION_TIMEOUT_OPTIONS = [0, 5, 10, 15, 30] as const;

export function AccountSettingsModule({ currentUser, onUpdated, headerHideMode, onHeaderHideModeChange }: AccountSettingsModuleProps) {
  const [name, setName] = useState(currentUser.name);
  const [email, setEmail] = useState(currentUser.email);
  const [sessionTimeout, setSessionTimeout] = useState(currentUser.session_timeout_minutes);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSaved, setPasswordSaved] = useState(false);

  const profileDirty =
    name !== currentUser.name || email !== currentUser.email || sessionTimeout !== currentUser.session_timeout_minutes;

  const handleSaveProfile = () => {
    if (!name.trim() || !email.trim()) return;
    setIsSavingProfile(true);
    setProfileError(null);
    setProfileSaved(false);
    updateMe({ name, email, session_timeout_minutes: sessionTimeout })
      .then(res => {
        onUpdated(res.data);
        setProfileSaved(true);
        setTimeout(() => setProfileSaved(false), 2500);
      })
      .catch(error => setProfileError(error instanceof Error ? error.message : "Failed to save changes."))
      .finally(() => setIsSavingProfile(false));
  };

  const handleChangePassword = () => {
    setPasswordError(null);
    setPasswordSaved(false);
    if (!currentPassword || !newPassword || !confirmPassword) {
      setPasswordError("Fill in all three password fields.");
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New password and confirmation do not match.");
      return;
    }

    setIsSavingPassword(true);
    updateMe({ current_password: currentPassword, new_password: newPassword })
      .then(res => {
        onUpdated(res.data);
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setPasswordSaved(true);
        setTimeout(() => setPasswordSaved(false), 2500);
      })
      .catch(error => setPasswordError(error instanceof Error ? error.message : "Failed to update password."))
      .finally(() => setIsSavingPassword(false));
  };

  return (
    <div className="h-full overflow-auto bg-background p-4">
      <div className="max-w-2xl mx-auto space-y-4">
        {/* Header */}
        <div>
          <h2 className="font-bold text-foreground flex items-center gap-2">
            <UserCog size={18} className="text-[#166534]" /> Account Settings
          </h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">Manage your own name, email, session timeout, and password.</p>
        </div>

        {/* Profile & Preferences */}
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-xs font-bold mb-3">Profile & Preferences</p>
          <div className="p-3 rounded-xl bg-muted/40 border border-border space-y-3">
            <div>
              <label className="text-[11px] font-semibold block mb-1">Full Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold block mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              />
              <p className="mt-1 text-[9px] text-muted-foreground">This is also your login email.</p>
            </div>
            <div>
              <label className="text-[11px] font-semibold block mb-1">Session Timeout</label>
              <select
                value={sessionTimeout}
                onChange={e => setSessionTimeout(Number(e.target.value))}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              >
                {SESSION_TIMEOUT_OPTIONS.map(v => <option key={v} value={v}>{v === 0 ? "Disabled" : `${v} minutes`}</option>)}
              </select>
              <p className="mt-1 text-[9px] text-muted-foreground">Auto-logout after this many idle minutes -- follows your account to any device.</p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3 justify-end">
            {profileSaved && <span className="text-[10px] text-emerald-600">Saved.</span>}
            {profileError && <span className="text-[10px] text-red-600">{profileError}</span>}
            <button
              onClick={handleSaveProfile}
              disabled={!profileDirty || !name.trim() || !email.trim() || isSavingProfile}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] disabled:opacity-50 transition-colors"
            >
              <Save size={11} /> {isSavingProfile ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>

        {/* Display Preferences (2026-08-18) -- client-only settings that
            apply immediately, no Save button: unlike Profile & Preferences
            above, none of this round-trips through updateMe()/SystemUser,
            so a Save/dirty-check flow would be misleading here. */}
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-xs font-bold mb-3">Display Preferences</p>
          <div className="p-3 rounded-xl bg-muted/40 border border-border space-y-3">
            <div>
              <label className="text-[11px] font-semibold block mb-1">Header Visibility</label>
              <select
                value={headerHideMode}
                onChange={e => onHeaderHideModeChange(e.target.value as HeaderHideMode)}
                className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
              >
                <option value="manual">Manual -- click a button to hide/show</option>
                <option value="auto">Auto-hide -- hides itself, hover to reveal</option>
              </select>
              <p className="mt-1 text-[9px] text-muted-foreground">
                Applies immediately. This device/browser only -- not saved to your account.
              </p>
            </div>
          </div>
        </div>

        {/* Change Password */}
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-xs font-bold mb-3">Change Password</p>
          <div className="p-3 rounded-xl bg-muted/40 border border-border space-y-3">
            {[
              { label: "Current Password", value: currentPassword, set: setCurrentPassword },
              { label: "New Password",     value: newPassword,     set: setNewPassword },
              { label: "Confirm New Password", value: confirmPassword, set: setConfirmPassword },
            ].map(f => (
              <div key={f.label}>
                <label className="text-[11px] font-semibold block mb-1">{f.label}</label>
                <input
                  type="password"
                  value={f.value}
                  onChange={e => f.set(e.target.value)}
                  className="w-full border border-border rounded-lg px-3 py-2 text-[11px] bg-background focus:outline-none focus:border-[#166534]"
                />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 mt-3 justify-end">
            {passwordSaved && <span className="text-[10px] text-emerald-600">Password updated.</span>}
            {passwordError && <span className="text-[10px] text-red-600">{passwordError}</span>}
            <button
              onClick={handleChangePassword}
              disabled={isSavingPassword}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] disabled:opacity-50 transition-colors"
            >
              <KeyRound size={11} /> {isSavingPassword ? "Updating…" : "Update Password"}
            </button>
          </div>
        </div>

        <div className="pb-6" />
      </div>
    </div>
  );
}
