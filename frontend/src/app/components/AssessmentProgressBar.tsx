import { Check, Loader2, X } from "lucide-react";
import { AssessmentJob, AssessmentStageStatus } from "@/lib/api";

// Real progress of one assessment calculation run (2026-10-22), from the
// backend job's own stage statuses and done/total counts -- never a timer.
// Shared by Assessment & Reporting and the Main Dashboard.

const STATUS_STYLE: Record<AssessmentStageStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  processing: "bg-[#ca8a04]/15 text-[#ca8a04] ring-1 ring-[#ca8a04]",
  completed: "bg-[#166534]/15 text-[#166534] dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400",
};

const STATUS_LABEL: Record<AssessmentStageStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

export function AssessmentProgressBar({ job }: { job: AssessmentJob }) {
  const failed = job.status === "error";
  const barColor = failed ? "#dc2626" : job.status === "done" ? "#166534" : "#ca8a04";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-semibold">
          {job.status === "done"
            ? "Assessment calculation complete"
            : failed
              ? `Failed during ${job.current_stage_label ?? "calculation"}`
              : `${job.current_stage_label ?? "Starting"}…`}
          {job.status === "processing" && job.stage_total > 0 && (
            <span className="font-normal text-muted-foreground"> ({job.stage_processed.toLocaleString()} / {job.stage_total.toLocaleString()})</span>
          )}
        </span>
        <span className="tabular-nums font-bold" style={{ color: barColor }}>{job.percent}%</span>
      </div>
      <div
        className="h-2 rounded-full bg-muted overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={job.percent}
      >
        <div className="h-full transition-[width] duration-300" style={{ width: `${job.percent}%`, background: barColor }} />
      </div>
      <div className="flex flex-wrap gap-1">
        {job.stages.map(stage => (
          <span key={stage.key} className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_STYLE[stage.status]}`}>
            {stage.status === "completed" && <Check size={10} strokeWidth={3} />}
            {stage.status === "processing" && <Loader2 size={10} className="animate-spin" />}
            {stage.status === "failed" && <X size={10} strokeWidth={3} />}
            {stage.label} · {STATUS_LABEL[stage.status]}
          </span>
        ))}
      </div>
      {failed && job.error && <p className="text-[10px] text-red-600">{job.error}</p>}
    </div>
  );
}
