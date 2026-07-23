import { useState, useRef, useEffect, useMemo } from "react";
import {
  UploadCloud, FileText, Map as MapIcon, ChevronUp, ChevronDown,
  Filter, ArrowUpDown, Download, AlertTriangle, CheckCircle2, Table2, Satellite
} from "lucide-react";
import { GISLeafletMap } from "./GISLeafletMap";
import { AOISARPanel } from "./AOISARPanel";
import { uploadCsv, uploadGpx, getFarms, getAssessments, Farm, Assessment, Bulletin } from "@/lib/api";

interface FarmRow extends Farm {
  assessment: Assessment | null;
}

type SortField = "farm_id" | "farmer_name" | "municipality" | "barangay" | "area_size";
type SortDir   = "asc" | "desc";

interface UploadedFile { name: string; size: string; type: "csv" | "gpx"; status: "ready" | "processing" | "done" | "error" }

interface SpatialAnalysisModuleProps {
  darkMode: boolean;
  selectedBulletin: Bulletin | null;
}

export function SpatialAnalysisModule({ darkMode, selectedBulletin }: SpatialAnalysisModuleProps) {
  const [farms, setFarms] = useState<Farm[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [isLoadingFarms, setIsLoadingFarms] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedFarmId, setSelectedFarmId] = useState<number | null>(null);
  const [showSARPanel, setShowSARPanel]      = useState(false);
  const [filterMuni, setFilterMuni] = useState("All");
  const [sortField, setSortField] = useState<SortField>("farm_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [topPanelH, setTopPanelH] = useState(55);
  const [showWarning, setShowWarning] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshFarms = () => {
    setIsLoadingFarms(true);
    setLoadError(null);
    getFarms()
      .then(res => setFarms(res.data))
      .catch(error => setLoadError(error instanceof Error ? error.message : "Failed to load farms."))
      .finally(() => setIsLoadingFarms(false));
  };

  useEffect(() => {
    refreshFarms();
    getAssessments().then(res => setAssessments(res.data)).catch(() => setAssessments([]));
  }, []);

  // Most recent assessment per farm_id (list_assessments() is ordered by assessment_date desc).
  const assessmentByFarmId = useMemo(() => {
    const map = new Map<number, Assessment>();
    for (const a of assessments) {
      if (a.farm_id != null && !map.has(a.farm_id)) map.set(a.farm_id, a);
    }
    return map;
  }, [assessments]);

  const farmRows: FarmRow[] = useMemo(
    () => farms.map(f => ({ ...f, assessment: assessmentByFarmId.get(f.farm_id) ?? null })),
    [farms, assessmentByFarmId]
  );

  const municipalities = useMemo(() => {
    const set = new Set(farmRows.map(f => f.municipality).filter((m): m is string => !!m));
    return ["All", ...Array.from(set).sort()];
  }, [farmRows]);

  const filteredFarms = farmRows
    .filter(f => filterMuni === "All" || f.municipality === filterMuni)
    .sort((a, b) => {
      const va = a[sortField] ?? "";
      const vb = b[sortField] ?? "";
      const cmp = typeof va === "number" && typeof vb === "number"
        ? va - vb
        : String(va).localeCompare(String(vb));
      return sortDir === "asc" ? cmp : -cmp;
    });

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    processFiles(files);
  };

  const processFiles = (files: File[]) => {
    files.forEach(file => {
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (ext !== "csv" && ext !== "gpx") {
        setShowWarning(`"${file.name}" is not a supported format. Please upload .csv or .gpx files.`);
        return;
      }
      const newFile: UploadedFile = {
        name: file.name,
        size: `${(file.size / 1024).toFixed(0)} KB`,
        type: ext as "csv" | "gpx",
        status: "processing",
      };
      setUploadedFiles(prev => [...prev, newFile]);

      if (ext === "csv") {
        uploadCsv(file)
          .then(result => {
            setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "done" } : f));
            setUploadStatus({
              type: "success",
              message: `${result.message} (${result.rows_inserted} inserted, ${result.rows_skipped} skipped)`,
            });
            refreshFarms();
          })
          .catch(error => {
            setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "error" } : f));
            setUploadStatus({
              type: "error",
              message: error instanceof Error ? error.message : "CSV upload failed.",
            });
          });
      } else {
        const targetFarm = farms.find(f => f.farm_id === selectedFarmId);
        if (!targetFarm || targetFarm.farmer_id == null) {
          setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "error" } : f));
          setShowWarning("Select a farm row in the table before uploading a GPX boundary file.");
          return;
        }
        uploadGpx(file, targetFarm.farmer_id, targetFarm.farm_id)
          .then(() => {
            setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "done" } : f));
            setUploadStatus({
              type: "success",
              message: `GPX boundary uploaded for Farm #${targetFarm.farm_id}.`,
            });
            refreshFarms();
          })
          .catch(error => {
            setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "error" } : f));
            setUploadStatus({
              type: "error",
              message: error instanceof Error ? error.message : "GPX upload failed.",
            });
          });
      }
    });
  };

  const handleExportPeriodOfExposure = () => {
    const headers = ["FARM_ID","FARMER","MUNICIPALITY","BARANGAY","AREA_HA","HAS_GPX_BOUNDARY","CROP_STAGE","WIND_SIGNAL","PERIOD_OF_EXPOSURE_HRS","FINAL_INDEMNITY_PAYMENT"];
    const rows = filteredFarms.map(f => [
      f.farm_id, f.farmer_name ?? "", f.municipality ?? "", f.barangay ?? "",
      f.area_size ?? "", f.location_geom ? "Yes" : "No",
      f.assessment?.crop_stage ?? "", f.assessment?.wind_velocity ?? "",
      f.assessment?.period_of_exposure ?? "", f.assessment?.final_indemnity_payment ?? "",
    ]);
    const csv = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const uri = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    const a = document.createElement("a");
    a.setAttribute("href", uri);
    a.setAttribute("download", "period_of_exposure_report.csv");
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field
      ? sortDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />
      : <ArrowUpDown size={10} className="opacity-30" />;

  const signalColors: Record<number, string> = {
    2:"text-amber-600 font-bold", 3:"text-orange-600 font-bold", 4:"text-red-600 font-bold", 5:"text-red-800 font-bold",
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Warning Modal */}
      {showWarning && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-card border border-amber-300 rounded-xl shadow-2xl p-5 max-w-sm">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={16} className="text-amber-500" />
              <span className="text-sm font-semibold">Upload Warning</span>
            </div>
            <p className="text-xs text-muted-foreground mb-3">{showWarning}</p>
            <button
              onClick={() => setShowWarning(null)}
              className="w-full py-1.5 rounded-lg bg-[#166534] text-white text-xs font-semibold hover:bg-[#14532d] transition-colors"
            >
              OK
            </button>
          </div>
        </div>
      )}

      {/* Top Panel – GIS Map */}
      <div style={{ height: `${topPanelH}%` }} className="flex flex-col overflow-hidden">
        {/* Map toolbar */}
        <div className="flex items-center gap-3 px-4 py-2 bg-card border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <MapIcon size={14} className="text-[#166534]" />
            <span className="text-xs font-semibold">
              {selectedBulletin ? `${selectedBulletin.typhoon_name} Impact Map` : "Spatial Impact Map"}
            </span>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Filter size={11} className="text-muted-foreground" />
            <span className="text-[11px] text-muted-foreground">Filter map:</span>
            <select
              value={filterMuni}
              onChange={e => setFilterMuni(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {municipalities.map(m => <option key={m}>{m}</option>)}
            </select>
            <button
              onClick={handleExportPeriodOfExposure}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#1e3a5f] text-white text-[11px] font-medium hover:bg-[#172f4d] transition-colors"
            >
              <Download size={11} /> Export Period of Exposure
            </button>
            <button
              onClick={() => setShowSARPanel(v => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors border ${showSARPanel ? "bg-[#166534] text-white border-[#166534]" : "border-[#166534] text-[#166534] hover:bg-[#166534]/10"}`}
            >
              <Satellite size={11} /> SAR / GEE Analysis
            </button>
          </div>
        </div>

        {/* Map canvas + SAR panel overlay */}
        <div className="flex-1 overflow-hidden p-2 relative">
          <GISLeafletMap
            farms={filterMuni === "All" ? farmRows : farmRows.filter(f => f.municipality === filterMuni)}
            selectedFarmId={selectedFarmId}
            onSelectFarm={setSelectedFarmId}
            selectedBulletin={selectedBulletin}
            darkMode={darkMode}
          />
          {/* SAR AOI Panel — slides in over the map */}
          {showSARPanel && (
            <AOISARPanel
              onClose={() => setShowSARPanel(false)}
              geeProjectId="pcic-bicol-gee-2024"
              darkMode={darkMode}
            />
          )}
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className="h-1.5 bg-border cursor-row-resize hover:bg-[#166534]/50 transition-colors shrink-0 flex items-center justify-center"
        onMouseDown={e => {
          const startY = e.clientY;
          const startH = topPanelH;
          const move = (mv: MouseEvent) => {
            const delta = ((mv.clientY - startY) / window.innerHeight) * 100;
            setTopPanelH(Math.max(30, Math.min(70, startH + delta)));
          };
          document.addEventListener("mousemove", move);
          document.addEventListener("mouseup", () => document.removeEventListener("mousemove", move), { once:true });
        }}
      >
        <div className="w-8 h-0.5 rounded bg-muted-foreground/40" />
      </div>

      {/* Bottom Panel – Data Import + Table */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Drag-Drop + Uploaded Files */}
        <div className="w-64 shrink-0 flex flex-col border-r border-border overflow-hidden">
          <div className="px-3 py-2 border-b border-border bg-card shrink-0">
            <div className="flex items-center gap-1.5">
              <UploadCloud size={13} className="text-[#166534]" />
              <span className="text-[11px] font-semibold">Data Import</span>
            </div>
          </div>

          {/* Drop Zone */}
          <div
            className={`m-2 border-2 border-dashed rounded-xl p-3 text-center cursor-pointer transition-all ${isDragging ? "border-[#166534] bg-[#166534]/10" : "border-border hover:border-[#166534]/60 hover:bg-muted/30"}`}
            onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <UploadCloud size={20} className={`mx-auto mb-1.5 ${isDragging ? "text-[#166534]" : "text-muted-foreground"}`} />
            <p className="text-[10px] font-medium">Drop files here or click to browse</p>
            <p className="text-[9px] text-muted-foreground mt-0.5">
              .CSV farmer records &middot; .GPX farm polygon (select a farm row first)
            </p>
            <input
              ref={fileInputRef}
              type="file" accept=".csv,.gpx" multiple hidden
              onChange={e => { if (e.target.files) processFiles(Array.from(e.target.files)); }}
            />
          </div>

          {uploadStatus && (
            <div
              className="mx-2 mb-2 text-[10px] p-2 rounded-lg"
              style={{
                backgroundColor: uploadStatus.type === "success" ? "var(--sidebar-accent)" : "var(--destructive)",
                color: uploadStatus.type === "success" ? "var(--sidebar-accent-foreground)" : "white",
              }}
            >
              {uploadStatus.message}
            </div>
          )}

          {/* Uploaded / imported file indicators */}
          <div className="px-2 space-y-1.5 flex-1 overflow-auto">
            {uploadedFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-2 bg-card border border-border rounded-lg px-2.5 py-2">
                <FileText size={12} className={f.type === "csv" ? "text-blue-500" : "text-amber-500"} />
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] font-medium truncate">{f.name}</p>
                  <p className="text-[9px] text-muted-foreground">{f.size} · {f.type.toUpperCase()}</p>
                </div>
                {f.status === "done" && <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />}
                {f.status === "error" && <AlertTriangle size={12} className="text-red-500 shrink-0" />}
                {f.status === "processing" && (
                  <div className="w-3 h-3 rounded-full border-2 border-[#166534] border-t-transparent animate-spin shrink-0" />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right: Farm Records Table */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card shrink-0 flex-wrap gap-y-1">
            <div className="flex items-center gap-1.5">
              <Table2 size={13} className="text-[#166534]" />
              <span className="text-[11px] font-semibold">Farm Records</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
                {isLoadingFarms ? "Loading…" : `${filteredFarms.length} records`}
              </span>
              {loadError && <span className="text-[10px] text-red-500">{loadError}</span>}
            </div>
            <div className="ml-auto text-[9px] text-muted-foreground">
              Click a row to select it as the GPX upload target &amp; highlight it on the map
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 z-10">
                <tr className="bg-[#166534] text-white">
                  {[
                    { label:"Farm ID",     field:"farm_id"     as SortField },
                    { label:"Farmer",      field:"farmer_name" as SortField },
                    { label:"Municipality",field:"municipality" as SortField },
                    { label:"Barangay",    field:"barangay"    as SortField },
                    { label:"Area (ha)",   field:"area_size"   as SortField },
                  ].map(col => (
                    <th
                      key={col.field}
                      className="px-2.5 py-2 text-left font-semibold cursor-pointer hover:bg-white/10 whitespace-nowrap"
                      onClick={() => handleSort(col.field)}
                    >
                      <span className="flex items-center gap-1">
                        {col.label} <SortIcon field={col.field} />
                      </span>
                    </th>
                  ))}
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">GPX Boundary</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Crop Stage</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Signal</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Exp (h)</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Est. Payment</th>
                </tr>
              </thead>
              <tbody>
                {filteredFarms.map(f => (
                  <tr
                    key={f.farm_id}
                    onClick={() => setSelectedFarmId(f.farm_id === selectedFarmId ? null : f.farm_id)}
                    className={`border-t border-border cursor-pointer transition-colors hover:bg-muted/50 ${f.farm_id === selectedFarmId ? "bg-[#166534]/10 border-l-2 border-l-[#166534]" : ""}`}
                  >
                    <td className="px-2.5 py-2 font-mono text-[#166534]">#{f.farm_id}</td>
                    <td className="px-2.5 py-2 font-medium whitespace-nowrap">{f.farmer_name ?? "—"}</td>
                    <td className="px-2.5 py-2">{f.municipality ?? "—"}</td>
                    <td className="px-2.5 py-2 text-muted-foreground">{f.barangay ?? "—"}</td>
                    <td className="px-2.5 py-2 text-right">{f.area_size != null ? f.area_size.toFixed(2) : "—"}</td>
                    <td className="px-2.5 py-2">
                      {f.location_geom
                        ? <span className="text-emerald-600 flex items-center gap-0.5"><CheckCircle2 size={10} />Yes</span>
                        : <span className="text-muted-foreground">No</span>
                      }
                    </td>
                    <td className="px-2.5 py-2">{f.assessment?.crop_stage ?? "Not yet assessed"}</td>
                    <td className={`px-2.5 py-2 ${f.assessment?.wind_velocity ? signalColors[f.assessment.wind_velocity] ?? "" : "text-muted-foreground"}`}>
                      {f.assessment?.wind_velocity ? `No. ${f.assessment.wind_velocity}` : "—"}
                    </td>
                    <td className="px-2.5 py-2 text-right">{f.assessment?.period_of_exposure ?? "—"}</td>
                    <td className="px-2.5 py-2 text-right font-medium">
                      {f.assessment ? `₱${f.assessment.final_indemnity_payment.toLocaleString()}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
