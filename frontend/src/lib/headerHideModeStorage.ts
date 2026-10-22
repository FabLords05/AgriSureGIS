// Persists the main header's hide-mode preference per logged-in user, not
// globally per browser -- same reasoning and pattern as themeStorage.ts's
// dark-mode persistence (2026-08-17): keyed by email so two different users
// sharing the same browser/device each keep their own preference. Purely
// local-only, no backend/DB involved -- the same user on a different device
// starts fresh there too, and Account Settings (SystemUser) has no field
// for this (2026-08-18, see AccountSettingsModule.tsx's "Display
// Preferences" card).

export type HeaderHideMode = "manual" | "auto";

const HEADER_HIDE_MODE_STORAGE_PREFIX = "agrisuregis_header_hide_mode_";

function keyFor(email: string): string {
  return HEADER_HIDE_MODE_STORAGE_PREFIX + email.toLowerCase();
}

export function loadPersistedHeaderHideMode(email: string): HeaderHideMode {
  try {
    return localStorage.getItem(keyFor(email)) === "auto" ? "auto" : "manual";
  } catch {
    return "manual";
  }
}

export function persistHeaderHideMode(email: string, mode: HeaderHideMode): void {
  try {
    localStorage.setItem(keyFor(email), mode);
  } catch {
    // no-op -- the choice still applies for the current tab, it just won't
    // survive a refresh.
  }
}
