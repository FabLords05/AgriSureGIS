import { useRef } from "react";
import { CheckCircle2, AlertTriangle, Loader2, UploadCloud } from "lucide-react";

// Result of the most recent CSV or GPX/GPKG import, kept in App.tsx so it
// survives switching tabs while an upload runs.
export interface ImportSummary {
  kind: "CSV" | "GPX";
  finishedAt: string;
  ok: boolean;
  message: string;
  // Labelled counts in display order, e.g. [["Inserted", 120], ["Duplicates", 3]]
  counts: [string, number][];
  failures: string[];
}

// Main Dashboard "Data Import / PCIC Data Upload" (2026-10-22) -- the Upload
// CSV / Upload GPX controls moved here from Spatial Analysis. Handlers and
// progress stay in App.tsx (see SpatialAnalysisModule's old note), so this is
// display only: the same validated backend ingestion runs as before.
export function DataImportPanel({
  csvUploadProgress, gpxUploadProgress, onCsvFileSelected, onGpxFilesSelected, lastImport, onViewDetails,
}: {
  csvUploadProgress: { processed: number; total: number } | null;
  gpxUploadProgress: { current: number; total: number } | null;
  onCsvFileSelected: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onGpxFilesSelected: (e: React.ChangeEvent<HTMLInputElement>) => void;
  lastImport: ImportSummary | null;
  onViewDetails: (failures: string[]) => void;
}) {
  const csvInputRef = useRef<HTMLInputElement>(null);
  const gpxInputRef = useRef<HTMLInputElement>(null);

  const csvPercent = csvUploadProgress && csvUploadProgress.total > 0
    ? Math.min(100, Math.round((csvUploadProgress.processed / csvUploadProgress.total) * 100))
    : 0;
  const gpxPercent = gpxUploadProgress && gpxUploadProgress.total > 0
    ? Math.min(100, Math.round((gpxUploadProgress.current / gpxUploadProgress.total) * 100))
    : 0;

  return (
    <div className="bg-card border border-border rounded-xl shrink-0">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <UploadCloud size={14} className="text-[#1e3a5f]" />
          <span className="text-sm font-semibold">Data Import / PCIC Data Upload</span>
        </div>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          PCIC insurance records (.csv) and farm boundaries (.gpx, .gpkg). Re-uploading the same file adds no duplicate records.
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-3 px-4 py-3">
        <div className="flex flex-col gap-1.5 flex-1 min-w-[140px]">
          <button
            onClick={() => csvInputRef.current?.click()}
            disabled={csvUploadProgress !== null}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1e3a5f] text-white text-[12px] font-medium hover:bg-[#172f4d] disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {csvUploadProgress ? <Loader2 size={12} className="animate-spin" /> : <UploadCloud size={12} />}
            {csvUploadProgress ? "Importing CSV…" : "Upload CSV"}
          </button>
          <input ref={csvInputRef} type="file" accept=".csv" hidden onChange={onCsvFileSelected} />
          {csvUploadProgress && (
            <div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full bg-[#1e3a5f] transition-[width] duration-300" style={{ width: `${csvPercent}%` }} />
              </div>
              <p className="text-[10px] text-muted-foreground mt-0.5 tabular-nums">
                {csvPercent}% · {csvUploadProgress.processed.toLocaleString()} / {csvUploadProgress.total.toLocaleString()} rows
              </p>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-1.5 flex-1 min-w-[140px]">
          <button
            onClick={() => gpxInputRef.current?.click()}
            disabled={gpxUploadProgress !== null}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1e3a5f] text-white text-[12px] font-medium hover:bg-[#172f4d] disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            {gpxUploadProgress ? <Loader2 size={12} className="animate-spin" /> : <UploadCloud size={12} />}
            {gpxUploadProgress ? "Importing GPX…" : "Upload GPX"}
          </button>
          <input ref={gpxInputRef} type="file" accept=".gpx,.gpkg" multiple hidden onChange={onGpxFilesSelected} />
          {gpxUploadProgress && (
            <div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full bg-[#1e3a5f] transition-[width] duration-300" style={{ width: `${gpxPercent}%` }} />
              </div>
              <p className="text-[10px] text-muted-foreground mt-0.5 tabular-nums">
                {gpxPercent}% · {gpxUploadProgress.current} / {gpxUploadProgress.total} file(s)
              </p>
            </div>
          )}
        </div>

        {lastImport && (
          <div className={`w-full flex items-start gap-2 px-3 py-2 rounded-lg border ${lastImport.ok ? "border-emerald-200 bg-emerald-50 dark:bg-emerald-950/30" : "border-amber-200 bg-amber-50 dark:bg-amber-950/30"}`}>
            {lastImport.ok
              ? <CheckCircle2 size={13} className="text-emerald-600 shrink-0 mt-0.5" />
              : <AlertTriangle size={13} className="text-amber-600 shrink-0 mt-0.5" />}
            <div className="text-[11px] min-w-0">
              <p className="font-semibold">Last {lastImport.kind} import · {lastImport.finishedAt}</p>
              <p className="text-muted-foreground">{lastImport.message}</p>
              {lastImport.counts.length > 0 && (
                <p className="mt-0.5 tabular-nums">
                  {lastImport.counts.map(([label, n]) => `${label}: ${n.toLocaleString()}`).join(" · ")}
                </p>
              )}
              {lastImport.failures.length > 0 && (
                <button onClick={() => onViewDetails(lastImport.failures)} className="mt-1 text-[10px] font-semibold text-[#1e3a5f] dark:text-blue-300 underline">
                  View {lastImport.failures.length} issue(s)
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
