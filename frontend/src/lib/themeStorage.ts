// Persists the dark-mode toggle per logged-in user, not globally per
// browser (2026-08-17) -- keyed by email so two different users sharing the
// same browser/device each keep their own preference instead of inheriting
// whichever one last set it. Deliberately local-only, no backend/DB
// involved: the same user on a *different* device starts fresh there too --
// nothing syncs, this purely stops one shared device from mixing users'
// preferences together.
//
// Same lazy-read/fail-safe pattern as authStorage.ts's user persistence --
// a storage failure (private browsing, quota, disabled) should never crash
// the app, it should just fall back to not-persisted-this-session.

const DARK_MODE_STORAGE_PREFIX = "agrisuregis_dark_mode_";

function keyFor(email: string): string {
  return DARK_MODE_STORAGE_PREFIX + email.toLowerCase();
}

export function loadPersistedDarkMode(email: string): boolean {
  try {
    return localStorage.getItem(keyFor(email)) === "true";
  } catch {
    return false;
  }
}

export function persistDarkMode(email: string, darkMode: boolean): void {
  try {
    localStorage.setItem(keyFor(email), String(darkMode));
  } catch {
    // no-op -- toggle still works for the current tab, it just won't
    // survive a refresh.
  }
}
