// PWA install support (2026-10-12). The browser fires `beforeinstallprompt`
// once, early -- usually before the user has even logged in -- so it's
// captured here at startup (see main.tsx) and held until InstallAppPrompt
// asks for it after login. Chrome/Edge/Android only; iOS Safari and Firefox
// never fire it (InstallAppPrompt shows manual steps for those instead).

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());

export function initPwaInstall() {
  window.addEventListener("beforeinstallprompt", e => {
    // Stops Chrome's own mini-infobar -- we show our own prompt after login.
    e.preventDefault();
    deferredPrompt = e as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });

  // Production build only -- a service worker under `vite dev` would keep
  // serving stale modules across hot reloads.
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Not fatal: the app works the same, it just can't be installed.
      });
    });
  }
}

export function subscribePwaInstall(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export const canPromptInstall = () => deferredPrompt !== null;

// Opens the browser's own install dialog. The event can only be used once,
// so it's dropped either way -- Chrome fires a fresh one later if needed.
export async function promptInstall(): Promise<boolean> {
  if (!deferredPrompt) return false;
  const evt = deferredPrompt;
  deferredPrompt = null;
  notify();
  await evt.prompt();
  const { outcome } = await evt.userChoice;
  return outcome === "accepted";
}

// True when running as the installed app (its own window), not a browser tab.
export function isStandalone(): boolean {
  return window.matchMedia("(display-mode: standalone)").matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true;
}

export function isIos(): boolean {
  const ua = navigator.userAgent;
  // iPadOS 13+ reports itself as a Mac -- touch support gives it away.
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}
