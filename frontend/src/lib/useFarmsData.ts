import { useEffect, useRef, useState } from "react";
import { getFarms, Farm } from "./api";

// Rows fetched per GET /api/farms/ page. Keeps a single request small even
// at Fabio's real dev dataset scale (~48,588 rows as of 2026-08-08).
const PAGE_SIZE = 100;
// Pause between background-completion page fetches, so the loop doesn't
// compete for bandwidth/DB load against a user actively scrolling/using the app.
const BACKGROUND_FETCH_DELAY_MS = 300;

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// Farms data cache -- IndexedDB, not localStorage.
//
// A first version of this cache used localStorage, which has a hard ~5-10MB
// per-origin quota. At demo scale (~589 farms) that was never a problem; at
// Fabio's real dev dataset (~48,588 farms), `localStorage.setItem()` started
// throwing QuotaExceededError partway through -- silently, since it was
// caught and treated as "best-effort cache, skip on failure." The result: a
// TINY, separate progress marker (see below) kept persisting successfully
// all the way to "done," while the (much larger) farms array cache silently
// froze at its last successful write (~16,800 of 48,588 rows) -- the two
// caches desynced, and every later refresh trusted the (accurate!) "done"
// progress marker and skipped re-fetching, permanently showing the stale,
// truncated 16,800-row snapshot. IndexedDB doesn't have that ~5-10MB wall
// (browsers generally allow a much larger, often disk-proportional quota),
// so it's the correct tool for caching a dataset this size client-side.
// ---------------------------------------------------------------------------
const DB_NAME = "agrisuregis";
const DB_VERSION = 1;
const FARMS_STORE = "farms_cache";
const FARMS_RECORD_KEY = "farms";

// One-time cleanup: the old localStorage-based farms cache from before this
// fix is now orphaned dead weight -- worse, since it was written right up
// to the quota wall, it could itself be occupying most of this origin's
// localStorage budget, risking *other* small localStorage writes (the
// progress marker below, authStorage.ts's session) failing too. Removed
// unconditionally, once, as soon as this module loads.
try {
  localStorage.removeItem("agrisuregis_farms_cache");
} catch {
  // no-op -- nothing to clean up if storage was never available
}

function openFarmsDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(FARMS_STORE)) {
        req.result.createObjectStore(FARMS_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function loadCachedFarms(): Promise<Farm[]> {
  try {
    const db = await openFarmsDb();
    return await new Promise<Farm[]>(resolve => {
      const tx = db.transaction(FARMS_STORE, "readonly");
      const req = tx.objectStore(FARMS_STORE).get(FARMS_RECORD_KEY);
      req.onsuccess = () => resolve(Array.isArray(req.result) ? req.result : []);
      req.onerror = () => resolve([]); // fail safe -- treat as "nothing cached"
    });
  } catch {
    // IndexedDB unavailable (very old browser, disabled, private-mode
    // restrictions) -- fail safe to "nothing cached," same as before.
    return [];
  }
}

async function persistFarmsCache(farms: Farm[]): Promise<void> {
  try {
    const db = await openFarmsDb();
    await new Promise<void>(resolve => {
      const tx = db.transaction(FARMS_STORE, "readwrite");
      tx.objectStore(FARMS_STORE).put(farms, FARMS_RECORD_KEY);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve(); // best-effort, same fail-safe philosophy as before
    });
  } catch {
    // Storage unavailable -- this cache is a best-effort speed-up, not
    // required for correctness, so silently skip persisting this update.
  }
}

// ---------------------------------------------------------------------------
// Fetch progress -- still localStorage, deliberately. This payload is tiny
// (`{phase, activeOffset, allOffset}`, a few dozen bytes) and never at risk
// of the quota problem above; keeping it separate from the (much larger)
// IndexedDB farms cache is what makes it possible to tell the two apart at
// all. Without this, a refresh re-walked the entire two-phase sequence from
// page 1 every time; with it, a refresh resumes from the exact phase/offset
// it was at -- if it had already finished, nothing is re-fetched at all.
//
// Key is versioned (`_v2`) so any progress persisted by the old,
// localStorage-cache-paired version of this hook is never read back and
// trusted against the new (empty, on first run) IndexedDB cache -- that
// combination would otherwise reproduce the exact desync bug this fixes:
// progress says "done," new cache has nothing, farms render as permanently
// empty. Starting the version-2 progress fresh forces one real walk instead.
// ---------------------------------------------------------------------------
interface FetchProgress {
  phase: Phase;
  activeOffset: number;
  allOffset: number;
}

const PROGRESS_CACHE_KEY = "agrisuregis_farms_progress_v2";
const FRESH_PROGRESS: FetchProgress = { phase: "active", activeOffset: 0, allOffset: 0 };

function loadCachedProgress(): FetchProgress {
  try {
    const raw = localStorage.getItem(PROGRESS_CACHE_KEY);
    if (!raw) return FRESH_PROGRESS;
    const parsed = JSON.parse(raw);
    const validPhase = parsed?.phase === "active" || parsed?.phase === "all" || parsed?.phase === "done";
    if (validPhase && typeof parsed.activeOffset === "number" && typeof parsed.allOffset === "number") {
      return parsed as FetchProgress;
    }
    return FRESH_PROGRESS;
  } catch {
    return FRESH_PROGRESS;
  }
}

function persistProgress(progress: FetchProgress): void {
  try {
    localStorage.setItem(PROGRESS_CACHE_KEY, JSON.stringify(progress));
  } catch {
    // best-effort, same as the farms cache above
  }
}

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
  // True until a first determination has been made (either the IndexedDB
  // cache read resolved with nothing left to fetch, or a first real page
  // has landed) -- the one case where a consumer has nothing to show yet.
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
  // Loaded synchronously (localStorage, tiny) -- determines the initial
  // phase/offset/hasMore/isComplete below. The (much larger) farms array
  // itself is seeded separately and asynchronously, see the mount effect.
  const cachedProgress = loadCachedProgress();
  const [isLoadingFirstPage, setIsLoadingFirstPage] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const [hasMore, setHasMore] = useState(cachedProgress.phase !== "done");
  const [isComplete, setIsComplete] = useState(cachedProgress.phase === "done");
  const [loadError, setLoadError] = useState<string | null>(null);

  // Seeded from the cached progress above (defaults to phase "active",
  // offset 0 when nothing was cached) -- resume() below continues from
  // exactly these values instead of always restarting at page 1.
  const phaseRef = useRef<Phase>(cachedProgress.phase);
  const activeOffsetRef = useRef(cachedProgress.activeOffset);
  const allOffsetRef = useRef(cachedProgress.allOffset);
  const fetchInFlightRef = useRef(false);
  // Mirrors `farms` state synchronously (see fetchNextPage's comment on why
  // this can't just be read back from `farms` itself) -- always the current
  // merged array, usable immediately without waiting on a render.
  const farmsRef = useRef<Farm[]>([]);
  // Set true once `farms` has real data from either the cache read or a
  // successful fetch -- fetchNextPage() uses this to tell "nothing to show
  // yet" (isLoadingFirstPage) apart from "already showing something, this
  // is just a background top-up" (isFetchingMore).
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

      // Tracked in a ref (not read back from `farms` state) because React 18
      // batches state updates -- `setFarms(prev => ...)`'s updater isn't
      // guaranteed to have run yet by the time the code below needs the
      // merged array to persist it. The ref is always synchronously current.
      const mergedFarms = mergeFarmsPage(farmsRef.current, res.data);
      farmsRef.current = mergedFarms;
      setFarms(mergedFarms);
      offsetRef.current = requestOffset + res.data.length;
      hasLoadedOnceRef.current = true;
      setLoadError(null);

      if (!res.has_more) {
        if (phaseRef.current === "active") {
          phaseRef.current = "all";
          allOffsetRef.current = 0;
        } else {
          // Await the final cache write before this page's phase="done" is
          // persisted below. Previously this write was fire-and-forget (via
          // a separate effect keyed on `farms`), which left a real gap: the
          // tiny progress marker persists synchronously, the instant this
          // function returns, while the (much larger) IndexedDB write could
          // still be in flight -- a reload landing in that gap seeds from a
          // stale/truncated cache and then never fetches again, because it
          // trusts the already-"done" progress marker. Only the page that
          // actually completes the walk needs to wait; every earlier page
          // keeps the fire-and-forget write below, since an interrupted
          // reload there just resumes normally instead of stalling forever.
          await persistFarmsCache(mergedFarms);
          phaseRef.current = "done";
          setHasMore(false);
          setIsComplete(true);
        }
      }
      if (phaseRef.current !== "done") {
        persistFarmsCache(mergedFarms); // best-effort, not awaited -- see above
      }
      persistProgress({
        phase: phaseRef.current,
        activeOffset: activeOffsetRef.current,
        allOffset: allOffsetRef.current,
      });
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

  // True restart -- used only by refresh() (a CSV/GPX upload), never on
  // mount. Resets both the in-memory cursors and the persisted progress, so
  // a page refresh that happens mid-upload-refresh resumes from *this*
  // fresh sequence, not stale pre-refresh progress.
  const start = (isRefresh: boolean) => {
    generationRef.current += 1;
    const myGeneration = generationRef.current;
    fetchInFlightRef.current = false; // release any stale lock from a superseded sequence
    phaseRef.current = "active";
    activeOffsetRef.current = 0;
    allOffsetRef.current = 0;
    setHasMore(true);
    setIsComplete(false);
    persistProgress(FRESH_PROGRESS);
    if (isRefresh) setIsRefreshing(true);
    fetchNextPage().then(() => runBackgroundLoop(myGeneration));
  };

  // Mount-time entry point -- continues from wherever phaseRef/offsetRefs
  // already are (seeded from the cached progress above), instead of
  // resetting them like start() does. If a previous session already
  // finished (phase "done"), this is a complete no-op: no requests at all.
  const resume = () => {
    if (phaseRef.current === "done") return;
    const myGeneration = generationRef.current;
    fetchNextPage().then(() => runBackgroundLoop(myGeneration));
  };

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      // Seed `farms` from the IndexedDB cache first (async, unlike the tiny
      // progress marker above) -- if a previous session's `farms` cache
      // exists, this is what makes them appear instantly instead of behind
      // a full re-fetch. Runs regardless of what phaseRef says, since it's
      // just populating display data, not deciding whether to fetch.
      const cached = await loadCachedFarms();
      if (cancelled) return;
      if (cached.length > 0) {
        farmsRef.current = mergeFarmsPage(farmsRef.current, cached);
        setFarms(farmsRef.current);
        hasLoadedOnceRef.current = true;
      }
      // Self-heal guard: "done" progress is only trustworthy if the cache it
      // was persisted alongside actually holds every row -- `allOffsetRef`
      // is the "all" phase's cumulative count when it finished, which
      // should equal the cached array's length if that page's cache write
      // truly landed. A mismatch here is exactly this bug's fingerprint (a
      // reload catching the IndexedDB write for the completing page still
      // in flight, after its progress had already persisted as "done") --
      // rather than trust a "done" that can't be verified, fall back to
      // resuming the "all" phase from scratch. Re-walking is safe (merge is
      // idempotent by farm_id) and is what actually recovers a stuck
      // install like this one, no manual cache-clearing required.
      if (phaseRef.current === "done" && farmsRef.current.length !== allOffsetRef.current) {
        phaseRef.current = "all";
        allOffsetRef.current = 0;
        setHasMore(true);
        setIsComplete(false);
        persistProgress({ phase: "all", activeOffset: activeOffsetRef.current, allOffset: 0 });
      }
      if (phaseRef.current === "done") {
        // Nothing left to fetch -- the cache read above is the only thing
        // this mount needed to do. Clears the "loading" state even though
        // fetchNextPage() (which normally does this) never runs.
        setIsLoadingFirstPage(false);
      }
      resume(); // no-ops if phase is already "done"
    })();
    return () => { cancelled = true; };
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
