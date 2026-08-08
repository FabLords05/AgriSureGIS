import { useEffect, useRef, useState } from "react";
import { getFarms, Farm } from "./api";

// Rows fetched per GET /api/farms/ page. At today's ~589-farm dataset this is
// ~6 pages per phase; keeps a single request small even as the table grows
// toward the ~24k-row scale the backend's CSV ingestion path has been
// benchmarked at.
const PAGE_SIZE = 100;
// Pause between background-completion page fetches, so the loop doesn't
// compete for bandwidth/DB load against a user actively scrolling/using the app.
const BACKGROUND_FETCH_DELAY_MS = 300;

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

// Merges a freshly-fetched page into the existing farm list by farm_id (new
// ids appended, existing ids updated in place) instead of replacing the
// array outright. This is what lets both phases below (and a CSV/GPX
// refresh) grow/update the shared cache without ever dropping farms already
// visible to a consumer -- old rows simply stay until fresh data for that
// same farm arrives. `farm_id asc` is both the backend's fetch order and
// this hook's own sort, so re-sorting after each merge keeps it stable.
function mergeFarmsPage(current: Farm[], page: Farm[]): Farm[] {
  const byId = new Map(current.map(f => [f.farm_id, f]));
  for (const f of page) byId.set(f.farm_id, f);
  return Array.from(byId.values()).sort((a, b) => a.farm_id - b.farm_id);
}

type Phase = "active" | "all" | "done";

export interface FarmsData {
  farms: Farm[];
  // True only until the very first page has ever landed -- the one case
  // where a consumer has nothing to show yet at all.
  isLoadingFirstPage: boolean;
  // True while a refresh() (CSV/GPX upload) is restarting the fetch from
  // scratch. Existing `farms` stay visible/interactive throughout.
  isRefreshing: boolean;
  // True while any subsequent page (scroll-requested or background-paced)
  // is in flight -- for a "Loading more…" style indicator.
  isFetchingMore: boolean;
  // True while there's still more data to eventually load (either phase).
  hasMore: boolean;
  // True once the complete dataset (every farm, active and inactive) has
  // finished loading -- aggregate stats over `farms` are only guaranteed
  // fully accurate once this is true.
  isComplete: boolean;
  loadError: string | null;
  // Restarts the fetch from page 1 (e.g. after a CSV/GPX upload). Existing
  // `farms` are left in place and merged over, never cleared first.
  refresh: () => void;
  // Requests the next page immediately instead of waiting for the
  // background loop's next paced iteration -- e.g. a consumer's infinite
  // scroll calling this as the user nears the bottom of a list. Shares the
  // same in-flight lock as the background loop, so a page is never
  // requested twice.
  requestMore: () => void;
}

// Shared farms data source: starts fetching as soon as `enabled` flips true
// (e.g. right after login, from App.tsx) and keeps going regardless of which
// screen/tab is currently visible, so by the time a user navigates to a
// screen that needs farm data, some or all of it is often already there.
//
// Fetches in two phases so that every consumer's needs are met without
// contradiction: screens that only care about currently-active-insurance
// farms (e.g. the Spatial Analysis table's default view) get that smaller,
// relevant set first and fast; screens that need the complete dataset for
// correct aggregate stats (e.g. Monitoring's "Total Farms" stat card) are
// only ever computed over `farms`, which keeps growing until `isComplete`.
// Phase "active" (active_only=true) runs first; once it's exhausted, phase
// "all" (active_only=false) restarts pagination from offset 0 to fill in
// the remainder -- this does re-fetch farms phase "active" already merged
// in (harmless no-ops via mergeFarmsPage), since the two phases' offsets
// aren't directly comparable once the WHERE clause differs.
export function useFarmsData(enabled: boolean): FarmsData {
  const [farms, setFarms] = useState<Farm[]>([]);
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [isComplete, setIsComplete] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const phaseRef = useRef<Phase>("active");
  const activeOffsetRef = useRef(0);
  const allOffsetRef = useRef(0);
  const fetchInFlightRef = useRef(false);
  const hasLoadedOnceRef = useRef(false);
  // Bumped on every restart (mount, refresh()). A page fetch already in
  // flight when a restart happens checks this on resolve and discards its
  // result instead of corrupting the new sequence's cursors.
  const generationRef = useRef(0);

  const fetchNextPage = async () => {
    if (fetchInFlightRef.current || phaseRef.current === "done") return;
    const myGeneration = generationRef.current;
    fetchInFlightRef.current = true;
    if (!hasLoadedOnceRef.current) setIsLoadingFirstPage(true);
    else setIsFetchingMore(true);

    try {
      const activeOnly = phaseRef.current === "active";
      const offsetRef = activeOnly ? activeOffsetRef : allOffsetRef;
      const requestOffset = offsetRef.current;
      const res = await getFarms({ limit: PAGE_SIZE, offset: requestOffset, active_only: activeOnly });
      if (myGeneration !== generationRef.current) return; // superseded by a restart -- discard

      setFarms(prev => mergeFarmsPage(prev, res.data));
      offsetRef.current = requestOffset + res.data.length;
      hasLoadedOnceRef.current = true;
      setLoadError(null);

      if (!res.has_more) {
        if (phaseRef.current === "active") {
          phaseRef.current = "all";
          allOffsetRef.current = 0;
        } else {
          phaseRef.current = "done";
          setHasMore(false);
          setIsComplete(true);
        }
      }
    } catch (error) {
      if (myGeneration !== generationRef.current) return;
      setLoadError(error instanceof Error ? error.message : "Failed to load farms.");
      // Stop retrying automatically; a manual refresh() (or reload) tries again.
      phaseRef.current = "done";
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

  const runBackgroundLoop = async (myGeneration: number) => {
    while (phaseRef.current !== "done" && myGeneration === generationRef.current) {
      await fetchNextPage();
      if (phaseRef.current === "done" || myGeneration !== generationRef.current) break;
      await sleep(BACKGROUND_FETCH_DELAY_MS);
    }
  };

  const start = (isRefresh: boolean) => {
    generationRef.current += 1;
    const myGeneration = generationRef.current;
    fetchInFlightRef.current = false; // release any stale lock from a superseded sequence
    phaseRef.current = "active";
    activeOffsetRef.current = 0;
    allOffsetRef.current = 0;
    setHasMore(true);
    setIsComplete(false);
    if (isRefresh) setIsRefreshing(true);
    fetchNextPage().then(() => runBackgroundLoop(myGeneration));
  };

  useEffect(() => {
    if (!enabled) return;
    start(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return {
    farms,
    isLoadingFirstPage,
    isRefreshing,
    isFetchingMore,
    hasMore,
    isComplete,
    loadError,
    refresh: () => start(true),
    requestMore: () => { fetchNextPage(); },
  };
}
