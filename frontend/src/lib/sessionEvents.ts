// Tiny window-event bridge so api.ts (a plain module, outside React) can
// tell App.tsx a request came back 401 without forcing a jarring, silent
// window.location.reload() -- App.tsx listens for this and shows an
// explicit "you've been logged out" notice instead, only navigating to the
// login screen once the user acknowledges it (see LoggedOutNotice.tsx).

export const SESSION_EXPIRED_EVENT = "agrisuregis:session-expired";

export function notifySessionExpired(): void {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}
