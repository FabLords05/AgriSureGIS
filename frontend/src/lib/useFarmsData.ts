import { useEffect, useRef, useState } from "react";
import { getFarms, Farm } from "./api";

// Rows fetched per GET /api/farms/ page -- 1000 is the backend's own max
// `limit` (farms.py: Query(..., le=1000)).
const PAGE_SIZE = 1000;

// ---------------------------------------------------------------------------
// Stage 2 of the on-demand-pagination redesign (2026-08-18, see
// .claude/FUNCTION_CHANGES.md) -- this hook used to eagerly background-walk
// the ENTIRE farms table to completion on every session (first an
// active-insurance phase, then an unfiltered "all" phase), regardless of
// what was actually on screen, caching the growing result into IndexedDB +
// a versioned localStorage progress marker to survive that walk across
// reloads. That was real waste at 100k-1M farm scale: minutes of pacing
// delay, unbounded IndexedDB growth, and it existed only because
// MonitoringModule.tsx needed the complete dataset for dashboard stats
// (now served by GET /api/assessments/summary instead, see
// MonitoringModule.tsx) and SpatialAnalysisModule.tsx had no way to scope
// what it asked for.
//
// This hook is now purely on-demand and filter-scoped: it fetches for any
// (activeOnly, municipality, farmerId) combination *except* one --
// `activeOnly: false, municipality: null, farmerId: null` ("every farm,
// active or not, no municipality or farmer scope") is the one combination
// that's genuinely unbounded at 100k-1M scale, so it's a no-op instead
// (`farms` stays whatever it already was, no new request). The default
// `activeOnly: true, municipality: null, farmerId: null` (App.tsx's
// initial state) fetches normally -- it's bounded by however many farms
// actually have active insurance, same as the original pre-redesign
// default view. A real `farmerId` (2026-08-18, farmer search) scopes
// exactly like a real `municipality` does -- a specific farmer's own farms
// are always a small, bounded set, so either one alone is enough to allow
// activeOnly: false. Once scoped, only page 1 fetches eagerly; every later
// page requires an explicit requestMore() call (SpatialAnalysisModule's
// existing scroll IntersectionObserver). No background pacing loop, no
// IndexedDB -- a filter-scoped page set is small enough that a plain
// re-fetch on remount/filter-change is cheap.
//
// One-time cleanup of any pre-existing state from the old model.
try {
  indexedDB.deleteDatabase("agrisuregis");
  localStorage.removeItem("agrisuregis_farms_progress_v3");
  localStorage.removeItem("agrisuregis_farms_cache"); // even older, pre-IndexedDB leftover
} catch {
  // no-op -- nothing to clean up if storage was never available
}

// Merges a freshly-fetched page into the existing farm list by farm_id (new
// ids appended, existing ids updated in place) instead of replacing the
// array outright -- lets a filter change or CSV/GPX refresh grow/update the
// shared list without dropping farms already visible to a consumer mid-fetch.
// `farm_id asc` is both the backend's fetch order and this hook's own sort,
// so re-sorting after each merge keeps it stable.
function mergeFarmsPage(current: Farm[], page: Farm[]): Farm[] {
  const byId = new Map(current.map(f => [f.farm_id, f]));
  for (const f of page) byId.set(f.farm_id, f);
  return Array.from(byId.values()).sort((a, b) => a.farm_id - b.farm_id);
}

export interface UseFarmsDataParams {
  enabled: boolean;
  activeOnly: boolean;
  // null = no municipality searched/picked yet. See App.tsx's
  // `filterMuni === "All" ? null : filterMuni`. Combined with activeOnly:
  // false AND farmerId: null, this is the one combination the hook refuses
  // to fetch for (see the module docstring) -- App.tsx guards against
  // staying in it (forces activeOnly back to true whenever both
  // municipality and farmerId revert to null).
  municipality: string | null;
  // null = no farmer searched/picked yet. Scopes exactly like municipality
  // -- either one alone is enough to allow activeOnly: false.
  farmerId: number | null;
}

export interface FarmsData {
  farms: Farm[];
  // True until a first determination has been made for the current
  // activeOnly/municipality combination -- false immediately (no perpetual
  // spinner) for the one unbounded combination the hook refuses to fetch.
  isLoadingFirstPage: boolean;
  // True while a refresh() (CSV/GPX upload) is restarting the fetch from
  // scratch. Existing `farms` stay visible/interactive throughout.
  isRefreshing: boolean;
  // True while a subsequent page (scroll-requested) is in flight -- for a
  // "Loading more…" style indicator.
  isFetchingMore: boolean;
  // True while there's still more data available for the current filters.
  hasMore: boolean;
  loadError: string | null;
  // Re-fetches page 1 under the *current* activeOnly/municipality (e.g.
  // after a CSV/GPX upload). Existing `farms` are left in place and merged
  // over, never cleared first.
  refresh: () => void;
  // Requests the next page immediately -- e.g. a consumer's infinite scroll
  // calling this as the user nears the bottom of a list. Shares the same
  // in-flight lock as any other fetch, so a page is never requested twice.
  requestMore: () => void;
}

export function useFarmsData({ enabled, activeOnly, municipality, farmerId }: UseFarmsDataParams): FarmsData {
  const [farms, setFarms] = useState<Farm[]>([]);
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const afterIdRef = useRef(0);
  const hasMoreRef = useRef(false);
  const fetchInFlightRef = useRef(false);
  // Mirrors `farms` state synchronously -- always the current merged array,
  // usable immediately without waiting on a render (React state updates
  // inside an in-flight async fetch aren't guaranteed to have landed yet).
  const farmsRef = useRef<Farm[]>([]);
  const hasLoadedOnceRef = useRef(false);
  // Bumped on every restart (mount/enable, filter change, refresh()). A page
  // fetch already in flight when a restart happens checks this on resolve
  // and discards its result instead of corrupting the new sequence's cursor.
  const generationRef = useRef(0);

  const fetchNextPage = async (myGeneration: number) => {
    if (fetchInFlightRef.current || !hasMoreRef.current) return;
    fetchInFlightRef.current = true;
    if (!hasLoadedOnceRef.current) setIsLoadingFirstPage(true);
    else if (afterIdRef.current > 0) setIsFetchingMore(true);

    try {
      const res = await getFarms({
        limit: PAGE_SIZE,
        after_id: afterIdRef.current,
        active_only: activeOnly,
        municipality: municipality ?? undefined,
        farmer_id: farmerId ?? undefined,
      });
      if (myGeneration !== generationRef.current) return; // superseded by a restart -- discard

      const merged = mergeFarmsPage(farmsRef.current, res.data);
      farmsRef.current = merged;
      setFarms(merged);
      // The cursor advances to the last (highest) farm_id actually
      // returned -- order_by(farm_id asc) on the backend guarantees that's
      // the correct "resume point". An empty page leaves the cursor
      // untouched; has_more will already be false in that case.
      if (res.data.length > 0) {
        afterIdRef.current = res.data[res.data.length - 1].farm_id;
      }
      hasLoadedOnceRef.current = true;
      setLoadError(null);
      hasMoreRef.current = res.has_more;
      setHasMore(res.has_more);
    } catch (error) {
      if (myGeneration !== generationRef.current) return;
      setLoadError(error instanceof Error ? error.message : "Failed to load farms.");
      // Stop retrying automatically; a manual refresh() (or filter change) tries again.
      hasMoreRef.current = false;
      setHasMore(false);
    } finally {
      if (myGeneration === generationRef.current) {
        fetchInFlightRef.current = false;
        setIsLoadingFirstPage(false);
        setIsFetchingMore(false);
        setIsRefreshing(false);
      }
    }
  };

  // Full restart: bumps generation (discards any in-flight page from
  // before this call), resets the cursor to 0, and fetches page 1 under
  // whatever activeOnly/municipality are current at call time. Existing
  // `farms` are left in place -- fetchNextPage's merge (not replace) means
  // old rows only disappear once nothing new matches them AND the caller's
  // own display filter (SpatialAnalysisModule's filteredFarms) excludes them.
  const start = () => {
    // No-op for the one combination that's genuinely unbounded at 100k-1M
    // scale: "every farm, active or not, no municipality or farmer scope"
    // (see the module docstring). Any other combination -- including the
    // default activeOnly=true/municipality=null/farmerId=null -- is fine
    // to fetch. Covers a CSV/GPX upload's refresh() firing while this
    // combination is briefly in effect (App.tsx's guard normally corrects
    // it before this matters).
    if (!activeOnly && municipality == null && farmerId == null) return;
    generationRef.current += 1;
    const myGeneration = generationRef.current;
    fetchInFlightRef.current = false;
    afterIdRef.current = 0;
    hasMoreRef.current = true;
    setHasMore(true);
    if (hasLoadedOnceRef.current) setIsRefreshing(true);
    fetchNextPage(myGeneration);
  };

  useEffect(() => {
    if (!enabled || (!activeOnly && municipality == null && farmerId == null)) {
      // Hook disabled, or the one unbounded combination (see start() above)
      // -- nothing to fetch. Bump generation so any in-flight fetch from a
      // just-changed filter discards its result instead of landing after this.
      generationRef.current += 1;
      fetchInFlightRef.current = false;
      afterIdRef.current = 0;
      hasMoreRef.current = false;
      hasLoadedOnceRef.current = false;
      farmsRef.current = [];
      setFarms([]);
      setHasMore(false);
      setIsLoadingFirstPage(false);
      setIsFetchingMore(false);
      setIsRefreshing(false);
      setLoadError(null);
      return;
    }
    start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, activeOnly, municipality, farmerId]);

  return {
    farms,
    isLoadingFirstPage,
    isRefreshing,
    isFetchingMore,
    hasMore,
    loadError,
    refresh: start,
    requestMore: () => fetchNextPage(generationRef.current),
  };
}
