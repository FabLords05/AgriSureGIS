// Persists the logged-in user across page refreshes and browser restarts.
//
// There is no real backend auth/session yet (LoginScreen.tsx checks against
// hardcoded demo credentials client-side, issues no token) -- App.tsx's
// `currentUser` was purely in-memory React state, which is why a refresh
// always bounced back to the login screen. This mirrors that same
// {name, role, email} shape into localStorage so it survives reloads, with
// no automatic expiry (per Fabio's direction) -- the session lasts until
// LogoutButton explicitly clears it.

export interface CurrentUser {
  name: string;
  role: string;
  email: string;
}

const STORAGE_KEY = "agrisuregis_current_user";

export function loadPersistedUser(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed === "object" && parsed !== null &&
      typeof parsed.name === "string" &&
      typeof parsed.role === "string" &&
      typeof parsed.email === "string"
    ) {
      return parsed as CurrentUser;
    }
    return null;
  } catch {
    // Corrupt/unparseable storage (e.g. a future/incompatible shape, or
    // localStorage unavailable in this context) -- fail safe to "not logged
    // in" rather than crash the app on load.
    return null;
  }
}

export function persistUser(user: CurrentUser): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Storage unavailable (private browsing, quota, disabled) -- login still
    // works for the current tab, it just won't survive a refresh.
  }
}

export function clearPersistedUser(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // no-op -- nothing to clear if storage was never available
  }
}
