// Persists the logged-in user (+ session token, as of 2026-08-16) across
// page refreshes and browser restarts.
//
// Login now issues a real signed session token (backend/app/core/security.py)
// that every other backend route requires via an Authorization: Bearer
// header (see api.ts's request()) -- this used to just be a plain
// {name, role, email} object with nothing backing it server-side. Storage
// has no automatic expiry here either (per Fabio's direction, session
// timeout is enforced client-side in App.tsx's idle timer, not by this
// module or the token's own fixed 24h safety-net expiry) -- the session
// lasts until the user explicitly logs out or goes idle past their
// account's configured threshold.

export interface CurrentUser {
  name: string;
  role: string;
  email: string;
  session_timeout_minutes: number;
}

const USER_STORAGE_KEY = "agrisuregis_current_user";
const TOKEN_STORAGE_KEY = "agrisuregis_session_token";

export function loadPersistedUser(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed === "object" && parsed !== null &&
      typeof parsed.name === "string" &&
      typeof parsed.role === "string" &&
      typeof parsed.email === "string" &&
      typeof parsed.session_timeout_minutes === "number"
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
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Storage unavailable (private browsing, quota, disabled) -- login still
    // works for the current tab, it just won't survive a refresh.
  }
}

export function clearPersistedUser(): void {
  try {
    localStorage.removeItem(USER_STORAGE_KEY);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // no-op -- nothing to clear if storage was never available
  }
}

export function loadPersistedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Same fallback as persistUser above.
  }
}
