import { useState, useEffect, useMemo, useRef } from "react";
import {
  Map as MapIcon, ChevronUp, ChevronDown,
  Filter, ArrowUpDown, UploadCloud, CheckCircle2, Table2, Satellite, ShieldCheck
} from "lucide-react";
import { GISLeafletMap } from "./GISLeafletMap";
import { AOISARPanel } from "./AOISARPanel";
import { getAssessments, uploadCsv, uploadGpx, Farm, Assessment, Bulletin } from "@/lib/api";
import { FarmsData } from "@/lib/useFarmsData";

interface FarmRow extends Farm {
  assessment: Assessment | null;
}

type SortField = "farm_id" | "farmer_name" | "municipality" | "barangay" | "area_size";
type SortDir   = "asc" | "desc";

// ---------------------------------------------------------------------------
// Farm Records table virtualization -- the shared farms cache can hold the
// entire ~48,588-row table (see useFarmsData.ts), and rendering all of them
// as real <tr> elements (once the full dataset lands, or "Active Insurance
// Only" is toggled off) meant tens of thousands of live DOM nodes + matching
// React fiber nodes mounted at once -- this is what was driving the browser
// tab's RAM into the 5-7GB range. Same idea as GISLeafletMap's viewport-bbox
// culling, applied to table scroll position instead of map bounds: only the
// rows currently scrolled into view (plus a small overscan buffer) are ever
// mounted as real <tr>s.
// ---------------------------------------------------------------------------
// Fixed row height (px), matching the table body's current px-2.5 py-2 /
// text-[11px] styling -- used only for the scroll-position math below, never
// applied via CSS. If the row's visual styling changes, update this to
// match; a slight mismatch only costs a few px of blank space at scroll
// boundaries (self-corrects on the next scroll tick), it doesn't break
// correctness.
const ROW_HEIGHT = 33;
// Extra rows rendered above/below the visible range so a fast scroll or key
// repeat doesn't show a blank flash before the next scroll event lands.
const OVERSCAN = 10;

interface SpatialAnalysisModuleProps {
  darkMode: boolean;
  selectedBulletin: Bulletin | null;
  // Shared with MonitoringModule and owned by App.tsx (useFarmsData) --
  // fetching starts the moment the app opens, not when this module mounts,
  // so data is often already there (or well underway) by the time a user
  // navigates here. See useFarmsData.ts for the fetch/pagination mechanics.
  farmsData: FarmsData;
}

export function SpatialAnalysisModule({ darkMode, selectedBulletin, farmsData }: SpatialAnalysisModuleProps) {
  const {
    farms,
    isLoadingFirstPage,
    isRefreshing,
    isFetchingMore,
    hasMore,
    loadError,
    refresh: refreshFarms,
    requestMore,
  } = farmsData;
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [selectedFarmId, setSelectedFarmId] = useState<number | null>(null);
  const [showSARPanel, setShowSARPanel]      = useState(false);
  const [filterMuni, setFilterMuni] = useState("All");
  // Defaults to true: a farm with no currently-active insurance policy is
  // rarely useful to look at day to day. This is purely a client-side
  // display filter over the shared `farms` cache -- toggling it does not
  // trigger a fetch, since useFarmsData already fetches active-insurance
  // farms first and the complete dataset shortly after, regardless of this
  // toggle's state (MonitoringModule's stat cards need the complete set
  // either way).
  const [activeInsuranceOnly, setActiveInsuranceOnly] = useState(true);
  const [muniQuery, setMuniQuery] = useState("");
  const [showMuniSuggestions, setShowMuniSuggestions] = useState(false);
  const [sortField, setSortField] = useState<SortField>("farm_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [topPanelH, setTopPanelH] = useState(55);
  const [uploadStatus, setUploadStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const gpxInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);
  // Drives the Farm Records table virtualization -- see the ROW_HEIGHT/
  // OVERSCAN comment above. tableViewportH starts at 0 (unmeasured); the
  // effect below fills it in as soon as scrollContainerRef exists and keeps
  // it current across resizes.
  const [tableScrollTop, setTableScrollTop] = useState(0);
  const [tableViewportH, setTableViewportH] = useState(0);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setTableViewportH(el.clientHeight);
    const observer = new ResizeObserver(() => setTableViewportH(el.clientHeight));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    getAssessments().then(res => setAssessments(res.data)).catch(() => setAssessments([]));
  }, []);

  // Infinite scroll: observe a sentinel row at the end of the table body and
  // request the next page immediately once it scrolls into view, instead of
  // waiting for useFarmsData's own background-paced loop to get there.
  // Re-attaches whenever the sentinel's presence in the DOM changes (first
  // page finishing load, or `hasMore` flipping) since IntersectionObserver
  // needs a live DOM node.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollContainerRef.current;
    if (!hasMore || !sentinel || !root) return;

    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) requestMore();
      },
      { root, rootMargin: "200px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
    // `requestMore` is a fresh function identity on every App-level re-render
    // (whenever useFarmsData's state changes, which happens on every page
    // fetch) -- excluded from deps so the observer isn't torn down/rebuilt
    // constantly; it always calls through to the same underlying fetch logic
    // regardless of which render's closure invoked it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMore, isLoadingFirstPage]);

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

  // Type-ahead suggestions for the municipality search box -- matches on the
  // typed letters as a prefix (case-insensitive), same idea as the old select
  // dropdown but searchable instead of scroll-to-find.
  const muniSuggestions = useMemo(() => {
    const options = municipalities.filter(m => m !== "All");
    const q = muniQuery.trim().toLowerCase();
    if (!q) return options;
    return options.filter(m => m.toLowerCase().startsWith(q));
  }, [municipalities, muniQuery]);

  const selectMunicipality = (m: string) => {
    setFilterMuni(m);
    setMuniQuery(m);
    setShowMuniSuggestions(false);
  };

  // Mirrors the "active" definition used by GET /api/insurance/summary:
  // today's date falls within effectivity_date-expiry_date, inclusive.
  // The API formats these as "MM/DD/YYYY" (farms.py), so they must be
  // parsed rather than compared as strings.
  const parseMDY = (s: string) => {
    const [month, day, year] = s.split("/").map(Number);
    return new Date(year, month - 1, day);
  };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isActiveInsurance = (f: Farm) =>
    f.effectivity_date != null && f.expiry_date != null &&
    parseMDY(f.effectivity_date) <= today && today <= parseMDY(f.expiry_date);

  // Memoized: this now also feeds the map (see the GISLeafletMap `farms`
  // prop below), so an unmemoized version would hand it a new array
  // reference on every unrelated re-render (e.g. typing in the
  // municipality search box), defeating the map's own memo chain.
  const filteredFarms = useMemo(
    () => farmRows
      .filter(f => filterMuni === "All" || f.municipality === filterMuni)
      .filter(f => !activeInsuranceOnly || isActiveInsurance(f))
      .sort((a, b) => {
        const va = a[sortField] ?? "";
        const vb = b[sortField] ?? "";
        const cmp = typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb));
        return sortDir === "asc" ? cmp : -cmp;
      }),
    [farmRows, filterMuni, activeInsuranceOnly, sortField, sortDir]
  );

  // Windowed slice of filteredFarms actually mounted as <tr>s -- see the
  // virtualization comment near ROW_HEIGHT/OVERSCAN above. Before the first
  // viewport-height measurement lands (tableViewportH still 0), falls back
  // to a fixed first batch instead of "everything," so the initial paint
  // never re-creates the DOM-blowup this is fixing.
  const tableStartIndex = tableViewportH > 0
    ? Math.max(0, Math.floor(tableScrollTop / ROW_HEIGHT) - OVERSCAN)
    : 0;
  const tableVisibleCount = tableViewportH > 0
    ? Math.ceil(tableViewportH / ROW_HEIGHT) + OVERSCAN * 2
    : Math.min(filteredFarms.length, 50);
  const tableEndIndex = Math.min(filteredFarms.length, tableStartIndex + tableVisibleCount);
  const windowedFarms = filteredFarms.slice(tableStartIndex, tableEndIndex);
  const topSpacerHeight = tableStartIndex * ROW_HEIGHT;
  const bottomSpacerHeight = (filteredFarms.length - tableEndIndex) * ROW_HEIGHT;

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  };

  const handleCsvFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same filename later
    if (!file) return;

    uploadCsv(file)
      .then(result => {
        const failedSuffix = result.rows_failed > 0 ? `, ${result.rows_failed} failed` : "";
        setUploadStatus({
          type: "success",
          message: `${result.message} (${result.rows_inserted} inserted, ${result.rows_skipped} skipped${failedSuffix})`,
        });
        refreshFarms();
      })
      .catch(error => {
        setUploadStatus({
          type: "error",
          message: error instanceof Error ? error.message : "CSV upload failed.",
        });
      });
  };

  // Farmer/farm for each file is auto-detected from its filename (see
  // GpxFarmerMatcherService) -- uploaded one at a time, not in parallel, so a
  // large batch doesn't hammer the backend all at once.
  const handleGpxFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-selecting the same filename(s) later
    if (files.length === 0) return;

    let succeeded = 0;
    const failures: string[] = [];
    for (const file of files) {
      try {
        await uploadGpx(file);
        succeeded++;
      } catch (error) {
        failures.push(`${file.name}: ${error instanceof Error ? error.message : "upload failed"}`);
      }
    }

    setUploadStatus(
      failures.length === 0
        ? { type: "success", message: `Uploaded ${succeeded} GPX file(s) successfully.` }
        : { type: "error", message: `${succeeded} succeeded, ${failures.length} failed — ${failures.join("; ")}` }
    );
    refreshFarms();
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
            <div className="relative">
              <input
                type="text"
                value={muniQuery}
                placeholder={filterMuni === "All" ? "All municipalities" : filterMuni}
                onChange={e => {
                  const value = e.target.value;
                  setMuniQuery(value);
                  setShowMuniSuggestions(true);
                  if (value.trim() === "") setFilterMuni("All");
                }}
                onFocus={() => setShowMuniSuggestions(true)}
                onBlur={() => setShowMuniSuggestions(false)}
                className="text-[11px] border border-border rounded px-2 py-1 bg-background w-40"
              />
              {showMuniSuggestions && muniSuggestions.length > 0 && (
                <div className="absolute top-full left-0 mt-1 w-40 max-h-48 overflow-auto bg-card border border-border rounded-lg shadow-lg z-20">
                  {muniSuggestions.map(m => (
                    <button
                      key={m}
                      onMouseDown={() => selectMunicipality(m)}
                      className={`w-full text-left px-2 py-1.5 text-[11px] hover:bg-muted transition-colors ${m === filterMuni ? "bg-[#166534]/10 font-semibold text-[#166534]" : ""}`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => csvInputRef.current?.click()}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#1e3a5f] text-white text-[11px] font-medium hover:bg-[#172f4d] transition-colors"
            >
              <UploadCloud size={11} /> Upload CSV
            </button>
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv"
              hidden
              onChange={handleCsvFileSelected}
            />
            <button
              onClick={() => gpxInputRef.current?.click()}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#1e3a5f] text-white text-[11px] font-medium hover:bg-[#172f4d] transition-colors"
            >
              <UploadCloud size={11} /> Upload GPX
            </button>
            <input
              ref={gpxInputRef}
              type="file"
              accept=".gpx"
              multiple
              hidden
              onChange={handleGpxFilesSelected}
            />
            <button
              onClick={() => setShowSARPanel(v => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors border ${showSARPanel ? "bg-[#166534] text-white border-[#166534]" : "border-[#166534] text-[#166534] hover:bg-[#166534]/10"}`}
            >
              <Satellite size={11} /> SAR / GEE Analysis
            </button>
          </div>
        </div>

        {uploadStatus && (
          <div
            className="mx-4 mt-2 text-[10px] p-2 rounded-lg shrink-0"
            style={{
              backgroundColor: uploadStatus.type === "success" ? "var(--sidebar-accent)" : "var(--destructive)",
              color: uploadStatus.type === "success" ? "var(--sidebar-accent-foreground)" : "white",
            }}
          >
            {uploadStatus.message}
          </div>
        )}

        {/* Map canvas + SAR panel overlay */}
        <div className="flex-1 overflow-hidden p-2 relative">
          <GISLeafletMap
            farms={filteredFarms}
            selectedFarmId={selectedFarmId}
            onSelectFarm={setSelectedFarmId}
            selectedBulletin={selectedBulletin}
            darkMode={darkMode}
            focusMunicipality={filterMuni === "All" ? null : filterMuni}
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

      {/* Bottom Panel – Farm Records Table */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card shrink-0 flex-wrap gap-y-1">
            <div className="flex items-center gap-1.5">
              <Table2 size={13} className="text-[#166534]" />
              <span className="text-[11px] font-semibold">Farm Records</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
                {isLoadingFirstPage ? "Loading…" : isRefreshing ? "Refreshing…" : `${filteredFarms.length} records`}
              </span>
              {loadError && <span className="text-[10px] text-red-500">{loadError}</span>}
            </div>
            <button
              onClick={() => setActiveInsuranceOnly(v => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors border ${activeInsuranceOnly ? "bg-[#166534] text-white border-[#166534]" : "border-[#166534] text-[#166534] hover:bg-[#166534]/10"}`}
            >
              <ShieldCheck size={11} /> Active Insurance Only
            </button>
            <div className="ml-auto text-[9px] text-muted-foreground">
              Click a row to zoom the map to that farm
            </div>
          </div>

          <div
            className="flex-1 overflow-auto"
            ref={scrollContainerRef}
            onScroll={e => setTableScrollTop(e.currentTarget.scrollTop)}
          >
            {isLoadingFirstPage ? (
              <div className="flex items-center justify-center h-full text-[11px] text-muted-foreground">
                Loading farm records…
              </div>
            ) : (
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
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Effective Date</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Expiry Date</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Crop Stage</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Signal</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Exp (h)</th>
                  <th className="px-2.5 py-2 text-left font-semibold whitespace-nowrap">Est. Payment</th>
                </tr>
              </thead>
              <tbody>
                {/* Top spacer -- stands in for the rows scrolled past above
                    the window, so the scrollbar's size/position stays
                    correct for the full filteredFarms count even though only
                    windowedFarms below are real <tr>s. See the
                    virtualization comment near ROW_HEIGHT/OVERSCAN above. */}
                {topSpacerHeight > 0 && (
                  <tr aria-hidden style={{ height: topSpacerHeight }}>
                    <td colSpan={12} />
                  </tr>
                )}
                {windowedFarms.map(f => (
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
                    <td className="px-2.5 py-2 text-muted-foreground whitespace-nowrap">{f.effectivity_date ?? "—"}</td>
                    <td className="px-2.5 py-2 text-muted-foreground whitespace-nowrap">{f.expiry_date ?? "—"}</td>
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
                {/* Bottom spacer -- same purpose as the top one, for rows not
                    yet scrolled to below the window. */}
                {bottomSpacerHeight > 0 && (
                  <tr aria-hidden style={{ height: bottomSpacerHeight }}>
                    <td colSpan={12} />
                  </tr>
                )}
                {hasMore && (
                  <tr ref={sentinelRef} className="h-9">
                    <td colSpan={12} className="text-center text-[10px] text-muted-foreground">
                      {isFetchingMore ? "Loading more…" : ""}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
