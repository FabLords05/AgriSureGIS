import { LogOut } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";

export type LogoutReason = "idle" | "expired";

const REASON_COPY: Record<LogoutReason, string> = {
  idle: "You've been signed out due to inactivity.",
  expired: "Your session has expired. Please log in again.",
};

interface LoggedOutNoticeProps {
  reason: LogoutReason;
  onAcknowledge: () => void;
}

// Shown instead of silently snapping back to the login screen after an
// involuntary logout (idle timeout or an expired/invalid session token --
// see App.tsx's logoutReason state). Deliberately has no Cancel/dismiss
// path -- Root is left uncontrolled by any onOpenChange, so Escape/outside
// click can't close it -- the only way through is the explicit click, so
// the user actually sees why they landed back at login instead of just
// finding themselves there.
export function LoggedOutNotice({ reason, onAcknowledge }: LoggedOutNoticeProps) {
  return (
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <LogOut size={18} className="text-muted-foreground" />
            You've Been Logged Out
          </AlertDialogTitle>
          <AlertDialogDescription>{REASON_COPY[reason]}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction onClick={onAcknowledge}>Return to Login</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
