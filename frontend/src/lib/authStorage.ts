// Persists the logged-in user (+ session token, as of 2026-08-16) across
// page refreshes -- but NOT past closing the app (2026-10-22, explicit
// request: closing the app logs out).
//
// Login now issues a real signed session token (backend/app/core/security.py)
// that every other backend route requires via an Authorization: Bearer
// header (see api.ts's request()) -- this used to just be a plain
// {name, role, email} object with nothing backing it server-side. Storage
// has no automatic expiry here either (per Fabio's direction, session
// timeout is enforced client-side in App.tsx's idle timer, not by this
// module or the token's own fixed 24h safety-net expiry) -- the session
// lasts until the user explicitly logs out, goes idle past their account's
// configured threshold, or closes the app.
//
// sessionStorage, not localStorage (2026-10-22): the browser keeps it across
// a refresh but discards it when the tab or the installed (PWA) app window is
// closed, so the next open lands on the login screen. Consequence: a second
// tab doesn't share the session and asks for login too. The token itself is
// stateless (no server-side blocklist), so a closed app sends no LOGOUT to the
// Activity Log -- there's no reliable "closing, not refreshing" signal to send
// it on -- the token is simply gone from the device.

export interface CurrentUser {
  name: string;
  role: string;
  email: string;
  session_timeout_minutes: number;
}

const USER_STORAGE_KEY = "agrisuregis_current_user";
const TOKEN_STORAGE_KEY = "agrisuregis_session_token";

// A session saved by a build before this change lives in localStorage and
// would otherwise sit on disk indefinitely; it's never read again, so drop it.
try {
  localStorage.removeItem(USER_STORAGE_KEY);
  localStorage.removeItem(TOKEN_STORAGE_KEY);
} catch {
  // Storage unavailable -- nothing to clean up.
}

export function loadPersistedUser(): CurrentUser | null {
  try {
    const raw = sessionStorage.getItem(USER_STORAGE_KEY);
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
    // sessionStorage unavailable in this context) -- fail safe to "not logged
    // in" rather than crash the app on load.
    return null;
  }
}

export function persistUser(user: CurrentUser): void {
  try {
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Storage unavailable (private browsing, quota, disabled) -- login still
    // works for the current page, it just won't survive a refresh.
  }
}

export function clearPersistedUser(): void {
  try {
    sessionStorage.removeItem(USER_STORAGE_KEY);
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // no-op -- nothing to clear if storage was never available
  }
}

export function loadPersistedToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Same fallback as persistUser above.
  }
}
