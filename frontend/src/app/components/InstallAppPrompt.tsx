import { useEffect, useState } from "react";
import { Download, Share, MoreVertical } from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { BrandLogo } from "./BrandLogo";
import {
  canPromptInstall, isIos, isStandalone, promptInstall, subscribePwaInstall,
} from "@/lib/pwaInstall";

// "Continue in browser" lasts for this tab only, so the prompt comes back on
// the next login until the app is installed. Wrapped in try/catch because
// sessionStorage can throw in locked-down/private browser modes.
const DISMISS_KEY = "pwaInstallDismissed";
const wasDismissed = () => { try { return sessionStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; } };
const markDismissed = () => { try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ } };

// Soft install gate (2026-10-12, per Fabio): shown after login whenever the
// app is open in a normal browser tab instead of as the installed PWA. Not a
// hard block -- Firefox can't install PWAs at all, and Chrome withholds its
// install prompt for a while after a dismissal, so a hard block would lock
// those users out. Same AlertDialog pattern as LoggedOutNotice.
export function InstallAppPrompt() {
  const [open, setOpen] = useState(() => !isStandalone() && !wasDismissed());
  const [canPrompt, setCanPrompt] = useState(canPromptInstall);

  useEffect(() => subscribePwaInstall(() => setCanPrompt(canPromptInstall())), []);

  useEffect(() => {
    const onInstalled = () => {
      setOpen(false);
      toast.success("AgriSureGIS installed. Open it from your home screen or desktop.");
    };
    window.addEventListener("appinstalled", onInstalled);
    return () => window.removeEventListener("appinstalled", onInstalled);
  }, []);

  if (!open) return null;

  const dismiss = () => { markDismissed(); setOpen(false); };
  const ios = isIos();

  return (
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <BrandLogo size={28} />
            Install AgriSureGIS
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="space-y-2">
              <p>Install the app for a full-screen window and a shortcut on your home screen or desktop.</p>
              {ios ? (
                <p className="flex flex-wrap items-center gap-1">
                  In Safari, tap <Share size={14} className="inline" /> <b>Share</b>, then <b>Add to Home Screen</b>.
                  You will need to log in once more inside the installed app.
                </p>
              ) : !canPrompt ? (
                <p className="flex flex-wrap items-center gap-1">
                  Open the browser menu <MoreVertical size={14} className="inline" /> and choose <b>Install app</b>.
                  If it isn't there, your browser doesn't support installing apps; use Chrome or Edge.
                </p>
              ) : null}
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={dismiss}>Continue in browser</AlertDialogCancel>
          {!ios && canPrompt && (
            <AlertDialogAction
              onClick={async e => {
                // Keep the dialog up until the browser's own dialog resolves.
                e.preventDefault();
                if (await promptInstall()) setOpen(false);
                else dismiss();
              }}
            >
              <Download size={14} /> Install
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
