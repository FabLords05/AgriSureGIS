import { useState, useRef } from "react";
import {
  UploadCloud, FileText, Map as MapIcon, ChevronUp, ChevronDown,
  Filter, ArrowUpDown, Download, AlertTriangle, CheckCircle2, Table2, Satellite
} from "lucide-react";
import { GISLeafletMap } from "./GISLeafletMap";
import { AOISARPanel } from "./AOISARPanel";
import { mockFarmers, FarmerRecord, GrowthStage } from "./mockData";
import { uploadCsv } from "@/lib/api";

type SortField = keyof FarmerRecord;
type SortDir   = "asc" | "desc";

interface UploadedFile { name: string; size: string; type: "csv" | "gpx"; status: "ready" | "processing" | "done" | "error" }

interface SpatialAnalysisModuleProps {
  darkMode: boolean;
}

const MUNICIPALITIES = ["All", "Naga City", "Pili", "Libmanan", "Sipocot", "Goa", "Lagonoy"];
const GROWTH_STAGES: (GrowthStage | "All")[] = ["All", "Seedling", "Vegetative", "Reproductive", "Ripening"];

export function SpatialAnalysisModule({ darkMode }: SpatialAnalysisModuleProps) {
  const [farmers, setFarmers] = useState<FarmerRecord[]>(mockFarmers);
  const [selectedFarmId, setSelectedFarmId] = useState<string | null>(null);
  const [showSARPanel, setShowSARPanel]      = useState(false);
  const [filterMuni, setFilterMuni] = useState("All");
  const [filterStage, setFilterStage] = useState<GrowthStage | "All">("All");
  const [filterPlanted, setFilterPlanted] = useState<"All" | "Yes" | "No">("All");
  const [sortField, setSortField] = useState<SortField>("rowId");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [topPanelH, setTopPanelH] = useState(55);
  const [showWarning, setShowWarning] = useState<string | null>(null);
  const [csvUploadStatus, setCsvUploadStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const filteredFarmers = farmers
    .filter(f => filterMuni === "All" || f.municipality === filterMuni)
    .filter(f => filterStage === "All" || f.growthStage === filterStage)
    .filter(f => filterPlanted === "All" || (filterPlanted === "Yes" ? f.planted : !f.planted))
    .sort((a, b) => {
      const va = a[sortField]; const vb = b[sortField];
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
            setCsvUploadStatus({
              type: "success",
              message: `${result.message} (${result.rows_inserted} inserted, ${result.rows_skipped} skipped)`,
            });
          })
          .catch(error => {
            setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "error" } : f));
            setCsvUploadStatus({
              type: "error",
              message: error instanceof Error ? error.message : "CSV upload failed.",
            });
          });
      } else {
        // GPX ingestion has no backend endpoint yet — kept as a visual-only placeholder.
        setTimeout(() => {
          setUploadedFiles(prev => prev.map(f => f.name === newFile.name ? { ...f, status: "done" } : f));
        }, 1500);
      }
    });
  };

  const handleExportPeriodOfExposure = () => {
    const headers = ["ROW_ID","FARMER_ID","INSURED_NAME","MUNICIPALITY","BARANGAY","FARM_ID","AREA_HA","PLANTED","PLANTING_DATE","GROWTH_STAGE","SIGNAL_NO","PERIOD_OF_EXPOSURE_HRS","WIND_VEL_MIN","WIND_VEL_MAX"];
    const rows = filteredFarmers.map(f => [
      f.rowId, f.farmerId, f.insuredName, f.municipality, f.barangay, f.farmId,
      f.areaHectare, f.planted ? "Yes":"No", f.plantingDate, f.growthStage,
      f.signalNo, f.periodOfExposure, f.windVelocityMin, f.windVelocityMax,
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

  const stageColors: Record<string, string> = {
    Seedling:"bg-green-100 text-green-700", Vegetative:"bg-emerald-100 text-emerald-700",
    Reproductive:"bg-yellow-100 text-yellow-700", Ripening:"bg-amber-100 text-amber-700",
  };

  const signalColors: Record<number, string> = {
    1:"text-emerald-600 font-bold", 2:"text-amber-600 font-bold", 3:"text-red-600 font-bold",
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
            <span className="text-xs font-semibold">Camarines Sur — Typhoon Pepito Impact Map</span>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Filter size={11} className="text-muted-foreground" />
            <span className="text-[11px] text-muted-foreground">Filter map:</span>
            <select
              value={filterMuni}
              onChange={e => setFilterMuni(e.target.value)}
              className="text-[11px] border border-border rounded px-2 py-1 bg-background"
            >
              {MUNICIPALITIES.map(m => <option key={m}>{m}</option>)}
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
            farmers={farmers}
            selectedFarmId={selectedFarmId}
            onSelectFarm={setSelectedFarmId}
            darkMode={darkMode}
            filterMunicipality={filterMuni === "All" ? undefined : filterMuni}
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
            <p className="text-[9px] text-muted-foreground mt-0.5">Accepts .CSV farmer records, .GPX farm polygons</p>
            <input
              ref={fileInputRef}
              type="file" accept=".csv,.gpx" multiple hidden
              onChange={e => { if (e.target.files) processFiles(Array.from(e.target.files)); }}
            />
          </div>

          {csvUploadStatus && (
            <div
              className="mx-2 mb-2 text-[10px] p-2 rounded-lg"
              style={{
                backgroundColor: csvUploadStatus.type === "success" ? "var(--sidebar-accent)" : "var(--destructive)",
                color: csvUploadStatus.type === "success" ? "var(--sidebar-accent-foreground)" : "white",
              }}
            >
              {csvUploadStatus.message}
            </div>
          )}

          {/* Uploaded / imported file indicators */}
          <div className="px-2 space-y-1.5 flex-1 overflow-auto">
            {[
              { name:"bicol_farmers_2024.csv",    size:"48 KB",  type:"csv" as const, status:"done" as const },
              { name:"camarines_sur_gpx.gpx",     size:"2.1 MB", type:"gpx" as const, status:"done" as const },
              ...uploadedFiles,
            ].map((f, i) => (
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

        {/* Right: Farmer Records Table */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card shrink-0 flex-wrap gap-y-1">
            <div className="flex items-center gap-1.5">
              <Table2 size={13} className="text-[#166534]" />
              <span className="text-[11px] font-semibold">Farmer Records</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">{filteredFarmers.length} records</span>
            </div>
            <div className="flex items-center gap-1.5 ml-auto flex-wrap gap-y-1">
              <select
                value={filterStage}
                onChange={e => setFilterStage(e.target.value as GrowthStage | "All")}
                className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background"
              >
                {GROWTH_STAGES.map(s => <option key={s}>{s}</option>)}
              </select>
              <select
                value={filterPlanted}
                onChange={e => setFilterPlanted(e.target.value as "All" | "Yes" | "No")}
                className="text-[10px] border border-border rounded px-1.5 py-0.5 bg-background"
              >
                {["All","Yes","No"].map(v => <option key={v}>Planted: {v}</option>)}
              </select>
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 z-10">
                <tr className="bg-[#166534] text-white">
                  {[
                    { label:"#",           field:"rowId"          as SortField },
                    { label:"Farmer ID",   field:"farmerId"       as SortField },
                    { label:"Insured Name",field:"insuredName"    as SortField },
                    { label:"Municipality",field:"municipality"   as SortField },
                    { label:"Barangay",    field:"barangay"       as SortField },
                    { label:"Farm ID",     field:"farmId"         as SortField },
                    { label:"Area (ha)",   field:"areaHectare"    as SortField },
                    { label:"Planted",     field:"planted"        as SortField },
                    { label:"Plant Date",  field:"plantingDate"   as SortField },
                    { label:"Stage",       field:"growthStage"    as SortField },
                    { label:"Signal",      field:"signalNo"       as SortField },
                    { label:"Exp (h)",     field:"periodOfExposure" as SortField },
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
                </tr>
              </thead>
              <tbody>
                {filteredFarmers.map(f => (
                  <tr
                    key={f.farmId}
                    onClick={() => setSelectedFarmId(f.farmId === selectedFarmId ? null : f.farmId)}
                    className={`border-t border-border cursor-pointer transition-colors hover:bg-muted/50 ${f.farmId === selectedFarmId ? "bg-[#166534]/10 border-l-2 border-l-[#166534]" : ""}`}
                  >
                    <td className="px-2.5 py-2 text-muted-foreground">{f.rowId}</td>
                    <td className="px-2.5 py-2 font-mono">{f.farmerId.slice(-5)}</td>
                    <td className="px-2.5 py-2 font-medium whitespace-nowrap">{f.insuredName}</td>
                    <td className="px-2.5 py-2">{f.municipality}</td>
                    <td className="px-2.5 py-2 text-muted-foreground">{f.barangay}</td>
                    <td className="px-2.5 py-2 font-mono text-[#166534]">{f.farmId}</td>
                    <td className="px-2.5 py-2 text-right">{f.areaHectare.toFixed(2)}</td>
                    <td className="px-2.5 py-2">
                      {f.planted
                        ? <span className="text-emerald-600 flex items-center gap-0.5"><CheckCircle2 size={10} />Yes</span>
                        : <span className="text-muted-foreground">No</span>
                      }
                    </td>
                    <td className="px-2.5 py-2 whitespace-nowrap text-muted-foreground">{f.plantingDate}</td>
                    <td className="px-2.5 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${stageColors[f.growthStage]}`}>{f.growthStage}</span>
                    </td>
                    <td className={`px-2.5 py-2 ${signalColors[f.signalNo]}`}>No. {f.signalNo}</td>
                    <td className="px-2.5 py-2 text-right">{f.periodOfExposure > 0 ? f.periodOfExposure : "—"}</td>
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
