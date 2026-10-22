import { clearPersistedUser, loadPersistedToken } from './authStorage';
import { notifySessionExpired } from './sessionEvents';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export interface Bulletin {
  tcb_id: number;
  typhoon_id: number;
  title: string;
  bulletin_count: number;
  category: string | null;
  typhoon_name: string;
  max_sustained_winds: string | null;
  gustiness: string | null;
  issued_at: string | null;
  center_lat: number | null;
  center_lng: number | null;
  // PAGASA's TCWS table as parsed, unvalidated against AdminBoundary:
  // { "<signal_level>": { "<island_group 0=Luzon|1=Visayas|2=Mindanao>": area text } }.
  // Null for bulletins with no TCWS table, or saved before this was stored.
  max_signal_level: number | null;
  tcws_areas: Record<string, Record<string, string>> | null;
  // PAGASA's final-bulletin marker (trailing "F" on the number, or an LPA
  // bulletin) -- the typhoon is ready for assessment once one arrives.
  is_final: boolean;
}

export interface GeoJsonMultiPolygon {
  type: "MultiPolygon";
  coordinates: number[][][][];
}

export interface Farm {
  farm_id: number;
  farmer_id: number | null;
  farmer_name: string | null;
  province: string | null;
  municipality: string | null;
  barangay: string | null;
  area_size: number | null;
  csv_farm_reference: string | null;
  georef_id: string | null;
  // Whether a GPX boundary has been uploaded -- actual polygon coordinates
  // are fetched separately via getFarmsGeometry(), never carried on this
  // type. See backend/app/api/farms.py's list_farms docstring (2026-08-18,
  // stage 2 of the on-demand-pagination redesign).
  has_geometry: boolean;
  // Shown as "CIC No." -- the newer PCIC CSV's CIC NO ("Policy No." in the legacy one).
  policy_no: string | null;
  amount_cover: number | null;
  program_type: string | null;
  effectivity_date: string | null;
  expiry_date: string | null;
  // Typhoon(s) this policy was locked as used for by a final PABS export,
  // e.g. "OPONG 2025". null = not used yet.
  used_for_typhoon: string | null;
}

export interface Assessment {
  assessment_id: number;
  policy_no: string | null;
  farm_id: number | null;
  amount_cover: number | null;
  crop_stage: string | null;
  period_of_exposure: number | null;
  wind_velocity: number | null;
  indemnity_factor: number | null;
  estimated_damage: number;
  final_indemnity_payment: number;
  assessment_date: string;
}

export interface CalculateAssessmentsResult {
  status: string;
  typhoon_id: number;
  bulletin_id: number;
  assessments_computed: number;
  assessments: Array<{
    assessment_id: number;
    insurance_records_id: number;
    crop_stage: string | null;
    period_of_exposure: number | null;
    wind_velocity: number | null;
    indemnity_factor: number | null;
    estimated_damage: number;
    final_indemnity_payment: number;
  }>;
}

export interface UploadGpxResult {
  status: string;
  message: string;
  farm_id: number;
  matched_by?: string | null;
  farmer_name?: string | null;
}

export interface UploadGpkgFeatureFailure {
  feature: number;
  file_name: string;
  farm_reference: string | null;
  error: string;
}

export interface UploadGpkgResult {
  status: string;
  message: string;
  features_total: number;
  features_updated: number;
  features_failed: number;
  duplicates_skipped: number;
  failures: UploadGpkgFeatureFailure[];
}

export interface UploadCsvRowFailure {
  row: number;
  policy_no: string | null;
  error: string;
}

export interface UploadCsvResult {
  status: string;
  message: string;
  rows_processed: number;
  rows_inserted: number;
  rows_skipped: number;
  rows_failed: number;
  failures: UploadCsvRowFailure[];
}

export interface ParseBulletinsResult {
  status: string;
  parsed_count: number;
  bulletins: Array<{ tcb_id: number; title: string; bulletin_count: number }>;
}

export interface ParserSettings {
  // Minutes, not hours (was polling_interval_hours until 2026-08-10).
  polling_interval_minutes: number;
}

export interface TcbSignal {
  signal_id: number;
  signal_level: number;
  island_group: number;
  area_name: string;
  // Null for signals saved before the nationwide PSGC expansion
  // (2026-08-20) -- see backend/migrations/2026-08-20_tcb_signal_province.sql.
  province: string | null;
}

export interface AreaExposureSummary {
  summary_id: number;
  boundary_id: number;
  province: string;
  municipality: string;
  max_signal_level: number;
  start_time: string;
  end_time: string;
  total_exposure_hours: number;
  is_eligible_6hr: boolean;
}

export interface ComputeExposureResult {
  status: string;
  typhoon_id: number;
  boundaries_computed: number;
  summaries: AreaExposureSummary[];
}

export interface TyphoonSummaryArea {
  province: string;
  municipality: string;
  max_signal_level: number;
  start_time: string;
  end_time: string;
  total_exposure_hours: number;
}

export interface TyphoonSummary {
  status: string;
  typhoon_id: number;
  typhoon_name: string;
  areas_hit: TyphoonSummaryArea[];
  max_signal_level: number | null;
  start_time: string | null;
  end_time: string | null;
  exposure_duration_hours: number | null;
  people_hit: number;
}

// Every request carries the session token now (2026-08-16) -- harmless on
// the two public routes (login/register) that ignore it, required by every
// other route's Depends(get_current_user)/require_admin (see
// backend/app/core/security.py). A 401 means the token is missing, expired
// past its fixed safety-net lifetime, or the account's since been
// deactivated -- any of those means "not really logged in anymore," so this
// force-clears local storage and notifies App.tsx (see sessionEvents.ts)
// rather than leaving the app sitting in a half-authenticated state. That
// used to be a hard window.location.reload() straight to the login screen;
// now App.tsx shows an explicit "you've been logged out" notice first (see
// LoggedOutNotice.tsx) so the user knows why they landed back at login
// instead of just finding themselves there. Login/register requests can 401
// legitimately (wrong password) -- excluded so a failed login attempt
// doesn't nuke storage that has nothing to clear anyway.
const _NO_FORCE_LOGOUT_PATHS = ['/api/users/login', '/api/users/register'];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = loadPersistedToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401 && !_NO_FORCE_LOGOUT_PATHS.includes(path)) {
      clearPersistedUser();
      notifySessionExpired();
    }
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// Real progress tracking (2026-08-16) -- CSV ingestion runs row-by-row on
// the backend already and is genuinely slow for a large real PABS export,
// so uploadCsv() now only starts the job (fast: file validation + parse)
// and returns a job_id immediately, instead of the request hanging until
// every row is done. Poll getCsvUploadStatus() for real percentage
// (processed/total), driven by the backend's actual row loop -- not a
// fake/simulated progress bar.
export interface StartCsvUploadResult {
  status: string;
  job_id: string;
  total_rows: number;
}

export function uploadCsv(file: File): Promise<StartCsvUploadResult> {
  const formData = new FormData();
  formData.append('file', file);
  return request<StartCsvUploadResult>('/api/upload/csv', {
    method: 'POST',
    body: formData,
  });
}

export interface CsvUploadStatus {
  status: 'processing' | 'done' | 'error';
  processed: number;
  total: number;
  result: UploadCsvResult | null;
  error: string | null;
}

export function getCsvUploadStatus(jobId: string): Promise<CsvUploadStatus> {
  return request<CsvUploadStatus>(`/api/upload/csv/status/${jobId}`);
}

export function getBulletins(): Promise<Bulletin[]> {
  return request<Bulletin[]>('/api/bulletins/');
}

export function parseBulletins(): Promise<ParseBulletinsResult> {
  return request<ParseBulletinsResult>('/api/bulletins/parse', { method: 'POST' });
}

export function getBulletinSignals(tcbId: number): Promise<TcbSignal[]> {
  return request<TcbSignal[]>(`/api/bulletins/${tcbId}/signals`);
}

export function computeExposure(tcbId: number): Promise<ComputeExposureResult> {
  return request<ComputeExposureResult>(`/api/bulletins/${tcbId}/compute-exposure`, { method: 'POST' });
}

// Reads the already-computed per-typhoon exposure summary (tbl_area_exposure_summary
// is populated once the typhoon's bulletins are done, not per-TCB) -- does not trigger
// a recompute.
export function getTyphoonSummary(typhoonId: number): Promise<TyphoonSummary> {
  return request<TyphoonSummary>(`/api/bulletins/typhoon/${typhoonId}/summary`);
}

export interface ActiveTyphoon {
  typhoon_id: number;
  name: string;
  year: number;
}

export interface ActiveTyphoonsResult {
  status: string;
  active_typhoons: ActiveTyphoon[];
}

// Reflects PAGASA's severe-weather-bulletin status page (PagasaStatusService),
// not TCB bulletin parsing -- see FUNCTION_CHANGES.md.
export function getActiveTyphoons(): Promise<ActiveTyphoonsResult> {
  return request<ActiveTyphoonsResult>('/api/typhoons/active');
}

// Spatial Analysis typhoon track overlay (2026-10-12) -- backend/app/api/typhoons.py's
// get_typhoon_track. One point per bulletin center, in issue order; radii are
// null for bulletins that didn't state them (or were saved before they were
// stored). in_par = latest center inside the PAR polygon (geometric, unlike
// TyphoonProgress.in_par); null when no bulletin has a center.
export interface TyphoonTrackPoint {
  tcb_id: number;
  bulletin_count: number;
  is_final: boolean;
  issued_at: string;
  category: string;
  max_sustained_winds: number | null;
  lat: number;
  lng: number;
  wind_radius_km: number | null;
  storm_force_radius_km: number | null;
  inside_par: boolean;
}

export interface TyphoonForecastPoint {
  label: string;
  lat: number;
  lon: number;
  location: string | null;
  inside_par: boolean;
}

export interface TyphoonTrack {
  status: string;
  typhoon_id: number;
  typhoon_name: string;
  year: number;
  is_active: boolean;
  par_polygon: [number, number][];
  points: TyphoonTrackPoint[];
  forecast: TyphoonForecastPoint[];
  in_par: boolean | null;
}

export function getTyphoonTrack(typhoonId: number): Promise<TyphoonTrack> {
  return request<TyphoonTrack>(`/api/typhoons/${typhoonId}/track`);
}

// Monitoring dashboard's typhoon progress strip -- backend/app/api/typhoons.py's
// get_typhoon_progress. in_par = still listed on PAGASA's status page.
export interface TyphoonProgress {
  status: string;
  typhoon_id: number;
  typhoon_name: string;
  in_par: boolean;
  bulletin_count: number;
  final_bulletin: { bulletin_count: number; issued_at: string } | null;
  exposure_areas: number;
  assessed_farms: number;
  exported_policies: number;
  exported_at: string | null;
}

export function getTyphoonProgress(typhoonId: number): Promise<TyphoonProgress> {
  return request<TyphoonProgress>(`/api/typhoons/${typhoonId}/progress`);
}

// Monitoring dashboard's System Status panel -- backend/app/api/system.py.
// parser.last_run_at is null until the first scheduled run after a backend
// restart (kept in memory only).
export interface SystemStatus {
  status: string;
  parser: {
    interval_minutes: number;
    last_run_at: string | null;
    scrape_ok: boolean | null;
    status_sync_ok: boolean | null;
    next_run_at: string | null;
  };
  last_bulletin: {
    tcb_id: number;
    bulletin_count: number;
    is_final: boolean;
    typhoon_name: string | null;
    issued_at: string;
  } | null;
  email_alerts: { configured: boolean };
  // Earth Engine connection for SAR planted verification (2026-10-12).
  // Read-only: the key itself lives only in backend/.env.
  gee: {
    configured: boolean;
    connected: boolean;
    project_id: string | null;
    service_account: string | null;
    last_error: string | null;
  };
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>('/api/system/status');
}

// Used only as a lightweight backend-connectivity ping by CalibrationModule's
// System Status section now -- the interval value it returns is no longer
// surfaced/editable in the UI (fixed backend-side, see scheduler.py).
export function getParserSettings(): Promise<ParserSettings> {
  return request<ParserSettings>('/api/bulletins/settings');
}

export function uploadGpx(file: File, farmerId?: number, farmId?: number): Promise<UploadGpxResult> {
  const formData = new FormData();
  formData.append('file', file);
  // Omitting both lets the backend auto-detect the farmer/farm from the filename.
  if (farmerId != null) formData.append('farmer_id', String(farmerId));
  if (farmId != null) formData.append('farm_id', String(farmId));
  return request<UploadGpxResult>('/api/upload/gpx', {
    method: 'POST',
    body: formData,
  });
}

// One .gpkg holds many farm boundaries -- each feature is matched to its farm
// by the backend from the feature's own FARMERSID/FARMID attributes.
export function uploadGpkg(file: File): Promise<UploadGpkgResult> {
  const formData = new FormData();
  formData.append('file', file);
  return request<UploadGpkgResult>('/api/upload/gpkg', {
    method: 'POST',
    body: formData,
  });
}

export interface GetFarmsResult {
  status: string;
  data: Farm[];
  // Only populated on the first page of a paginated walk (after_id === 0)
  // -- the backend skips recomputing this COUNT on every subsequent page to
  // avoid redoing it hundreds of times across a full walk. `null` on later
  // pages; unpaginated calls (no `limit`) still always populate it as
  // `data.length`. See backend/app/api/farms.py's docstring.
  total: number | null;
  limit: number | null;
  after_id: number;
  has_more: boolean;
}

// Omitting params returns the full, unpaginated farm list. Pass
// `limit`/`after_id` to page through the list, `active_only` to restrict to
// farms with a currently-active InsuranceRecord, `municipality` to restrict
// to one AdminBoundary.municipality, and `farmer_id` to restrict to one
// farmer's own farms (resolved via searchFarmers() below) -- see
// useFarmsData.ts and SpatialAnalysisModule.tsx. `municipality`/`farmer_id`
// combine (both, either, or neither), same as backend/app/api/farms.py.
// "Active" excludes policies locked as used by a final PABS export; pass
// `typhoon_id` to list the farms used for that typhoon instead (it overrides
// active_only -- see getUsedTyphoons() below).
//
// `after_id` is a keyset (cursor) position, not an OFFSET: pass the highest
// `farm_id` already seen (0 to start from the beginning). Unlike OFFSET,
// this costs the backend about the same regardless of how deep into a walk
// it is -- see backend/app/api/farms.py's docstring for the measured
// OFFSET-cost-grows-with-depth numbers this replaced.
export function getFarms(params?: {
  limit?: number;
  after_id?: number;
  active_only?: boolean;
  municipality?: string;
  farmer_id?: number;
  typhoon_id?: number;
  // Farms inside this typhoon's TCWS signal >= 2 areas in any of its
  // bulletins -- the "Affected by" filter (2026-10-12). Unlike typhoon_id
  // (already exported/locked as used), this works straight after a bulletin
  // is parsed, before any assessment run. AND's with the other filters.
  affected_typhoon_id?: number;
}): Promise<GetFarmsResult> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.after_id != null) query.set('after_id', String(params.after_id));
  if (params?.active_only != null) query.set('active_only', String(params.active_only));
  if (params?.municipality) query.set('municipality', params.municipality);
  if (params?.farmer_id != null) query.set('farmer_id', String(params.farmer_id));
  if (params?.typhoon_id != null) query.set('typhoon_id', String(params.typhoon_id));
  if (params?.affected_typhoon_id != null) query.set('affected_typhoon_id', String(params.affected_typhoon_id));
  const qs = query.toString();
  return request<GetFarmsResult>(`/api/farms/${qs ? `?${qs}` : ''}`);
}

// Viewport-scoped polygon fetch backing GISLeafletMap.tsx -- pass `bbox`
// ("minLon,minLat,maxLon,maxLat") for the normal moveend/zoomend case, or
// `farm_id` (which ignores bbox/active_only/municipality/farmer_id
// server-side) to resolve one specific farm's geometry regardless of the
// map's current viewport/filters -- e.g. FlyToSelectedFarm's out-of-view
// case. `farmer_id` without `bbox` similarly bypasses the viewport and
// returns every one of that farmer's farms, for flying to a searched
// farmer's farm(s) -- see backend/app/api/farms.py's get_farms_geometry
// docstring.
export interface FarmGeometry {
  farm_id: number;
  location_geom: GeoJsonMultiPolygon;
}

export interface GetFarmsGeometryResult {
  status: string;
  data: FarmGeometry[];
}

export function getFarmsGeometry(params: {
  bbox?: string;
  farm_id?: number;
  farmer_id?: number;
  active_only?: boolean;
  municipality?: string;
  typhoon_id?: number;
  // Same "Affected by" typhoon filter as getFarms -- keeps the map's polygons
  // scoped to exactly what the Farm Records table is showing.
  affected_typhoon_id?: number;
}): Promise<GetFarmsGeometryResult> {
  const query = new URLSearchParams();
  if (params.bbox) query.set('bbox', params.bbox);
  if (params.farm_id != null) query.set('farm_id', String(params.farm_id));
  if (params.farmer_id != null) query.set('farmer_id', String(params.farmer_id));
  if (params.active_only != null) query.set('active_only', String(params.active_only));
  if (params.municipality) query.set('municipality', params.municipality);
  if (params.typhoon_id != null) query.set('typhoon_id', String(params.typhoon_id));
  if (params.affected_typhoon_id != null) query.set('affected_typhoon_id', String(params.affected_typhoon_id));
  return request<GetFarmsGeometryResult>(`/api/farms/geometry?${query.toString()}`);
}

// Typhoons with at least one policy locked as used by a final PABS export --
// options for the Farm Records typhoon filter (2026-10-12).
export interface UsedTyphoon {
  typhoon_id: number;
  name: string;
  year: number;
  farm_count: number;
}

export function getUsedTyphoons(): Promise<{ status: string; data: UsedTyphoon[] }> {
  return request<{ status: string; data: UsedTyphoon[] }>('/api/farms/used-typhoons');
}

// Distinct municipality names for the Farm Records search box's suggestion
// list -- sourced from AdminBoundary, not from whatever farms happen to be
// loaded, so it's populated even before any municipality has been searched.
// See backend/app/api/farms.py's list_farm_municipalities docstring.
export function getMunicipalities(): Promise<{ status: string; data: string[] }> {
  return request<{ status: string; data: string[] }>('/api/farms/municipalities');
}

// Debounced farmer-name search backing the Farm Records search box's
// farmer field -- unlike municipalities, farmers can't be preloaded whole
// (tbl_farmers_profile scales with farm count), so the caller re-queries
// this per keystroke (with its own debounce) instead. See
// backend/app/api/farms.py's search_farmers docstring.
export interface FarmerSearchResult {
  farmer_id: number;
  name: string;
}

export function searchFarmers(q: string): Promise<{ status: string; data: FarmerSearchResult[] }> {
  return request<{ status: string; data: FarmerSearchResult[] }>(`/api/farms/farmers?q=${encodeURIComponent(q)}`);
}

export interface InsuranceSummary {
  status: string;
  active_count: number;
  total_count: number;
}

export function getInsuranceSummary(): Promise<InsuranceSummary> {
  return request<InsuranceSummary>('/api/insurance/summary');
}

// MonitoringModule.tsx's dashboard aggregate -- totals plus the two chart
// breakdowns, computed server-side (backend/app/api/assessments.py's
// get_assessments_summary) instead of reducing over the full farms array
// client-side. Deliberately not municipality-scoped -- see that function's
// docstring.
export interface GrowthStageBucket { crop_stage: string; farm_count: number }
export interface SignalBucket { wind_velocity: number; farm_count: number; total_area: number }

export interface AssessmentsSummary {
  status: string;
  total_farms: number;
  affected_farms: number;
  total_area: number;
  total_indemnity: number;
  growth_stage_distribution: GrowthStageBucket[];
  signal_breakdown: SignalBucket[];
}

export function getAssessmentsSummary(): Promise<AssessmentsSummary> {
  return request<AssessmentsSummary>('/api/assessments/summary');
}

export function getAssessments(typhoonId?: number, policyNo?: string): Promise<{ status: string; data: Assessment[] }> {
  const params = new URLSearchParams();
  if (typhoonId !== undefined) params.set('typhoon_id', String(typhoonId));
  if (policyNo !== undefined) params.set('policy_no', policyNo);
  const query = params.toString();
  return request<{ status: string; data: Assessment[] }>(`/api/assessments/${query ? `?${query}` : ''}`);
}

export function calculateAssessments(typhoonId: number, bulletinId: number): Promise<CalculateAssessmentsResult> {
  return request<CalculateAssessmentsResult>('/api/assessments/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ typhoon_id: typhoonId, bulletin_id: bulletinId }),
  });
}

// The backend names each export after its typhoon and the moment it was pulled
// (see backend/app/api/assessments.py's _export_filename), so the name it sends
// wins over the caller's. Reading it needs expose_headers=["Content-Disposition"]
// on the backend CORS middleware -- a cross-origin response hides the header
// otherwise, and we fall back to the caller's name (2026-10-12).
function filenameFromResponse(response: Response, fallback: string): string {
  const disposition = response.headers.get('Content-Disposition');
  const match = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return match ? match[1].trim() : fallback;
}

// Authenticated downloads (2026-10-11) -- the export routes sit on the
// assessments router, which is gated by Depends(get_current_user) (see
// backend/app/api/assessments.py:25), so they need the same Bearer header
// every other call carries. window.open()/<a href> is a plain top-level
// navigation: the browser sends no Authorization header, so the export tab
// rendered {"detail":"Not authenticated."} instead of saving a file.
// Fetching as a Blob and clicking a synthetic <a download> keeps the header
// and gives the same save-file behaviour.
async function downloadCsv(path: string, fallbackFilename: string, method: 'GET' | 'POST' = 'GET'): Promise<void> {
  const token = loadPersistedToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { method, headers });
  if (!response.ok) {
    if (response.status === 401) {
      clearPersistedUser();
      notifySessionExpired();
    }
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Download failed with status ${response.status}`);
  }

  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filenameFromResponse(response, fallbackFilename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export function downloadAssessmentsCsv(typhoonId: number): Promise<void> {
  return downloadCsv(`/api/assessments/export?typhoon_id=${typhoonId}`,
                     `assessments_typhoon_${typhoonId}.csv`);
}

// Combined export across every typhoon (not scoped to one bulletin/typhoon
// folder), in the PABS-required column format. P is PCIC's fixed "1.0", S the
// yield loss as a fraction ("0.3"), REMARKS PCIC's fixed sentence; no IRID
// (2026-10-12) -- see the backend's _build_pabs_rows docstring.
// POST: the backend locks every exported policy with a payout as used, so it
// can't be assessed again for a later typhoon.
export function downloadAssessmentsPabsCsv(): Promise<void> {
  return downloadCsv('/api/assessments/export-pabs', 'pabs_indemnity_export.csv', 'POST');
}

export interface PabsAssessmentRow {
  assessment_id: number;
  FARMER_NAME: string | null;
  FARMERID: string | null;
  // PCIC's own FARMID from the uploaded CSV (e.g. "1979999"), not farm_id.
  FARMID: string | null;
  // No source yet -- always blank (2026-10-12).
  IRID: string | null;
  CIC_NO: string | null;
  AREA: number | null;
  TYPHOON_NAME: string | null;
  PERIOD_OF_EXPOSURE: number | null;
  // km/h: the typhoon's max sustained winds across its bulletins (storm-wide).
  WIND_VELOCITY: number | null;
  AC: number | null;
  FINAL_INDEMNITY_PAYMENT: number | null;
  P: string;
  S: string | null;
  // PCIC's remark for the RECSAP cell; null when there is none.
  REMARKS: string | null;
  municipality: string | null;
  province: string | null;
  // On-screen only (not exported): the farm's barangay.
  barangay: string | null;
  // TCWS signal number (not exported) -- drives the on-screen Wind column.
  wind_signal: number | null;
  // On-screen only (not exported): assessed crop stage.
  crop_stage: string | null;
}

// JSON version of the same combined PABS-format summary, for on-screen display.
export function getAssessmentsPabsSummary(): Promise<{ status: string; data: PabsAssessmentRow[] }> {
  return request<{ status: string; data: PabsAssessmentRow[] }>('/api/assessments/pabs-summary');
}

// ─── System Users (real auth, replacing LoginScreen's old client-side
// DEMO_ACCOUNTS check) ────────────────────────────────────────────────────

export interface SystemUser {
  user_id: number;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  last_login: string | null;
  created_at: string | null;
  session_timeout_minutes: number;
}

export interface LoginResult {
  status: string;
  token: string;
  user: { name: string; role: string; email: string; session_timeout_minutes: number };
}

export function loginUser(email: string, password: string): Promise<LoginResult> {
  return request<LoginResult>('/api/users/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
}

// Doesn't touch the token itself (stateless JWT, no server-side blocklist --
// see backend/app/core/security.py) -- exists purely so a LOGOUT event gets
// recorded before the caller clears local storage. Fire-and-forget by
// design from App.tsx's handleLogout: logging out must never be blocked by
// a slow/failed network call.
export function logoutUser(): Promise<{ status: string }> {
  return request<{ status: string }>('/api/users/logout', { method: 'POST' });
}

export interface RegisterUserPayload {
  full_name: string;
  email: string;
  employee_id: string;
  role: string;
  password: string;
  division?: string;
}

export function registerUser(payload: RegisterUserPayload): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>('/api/users/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function getUsers(): Promise<{ status: string; data: SystemUser[] }> {
  return request<{ status: string; data: SystemUser[] }>('/api/users/');
}

export interface CreateUserPayload {
  name: string;
  email: string;
  role: string;
  password: string;
}

export function createUser(payload: CreateUserPayload): Promise<{ status: string; data: SystemUser }> {
  return request<{ status: string; data: SystemUser }>('/api/users/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export interface UpdateUserPayload {
  name?: string;
  email?: string;
  role?: string;
  is_active?: boolean;
  session_timeout_minutes?: number;
}

export function updateUser(userId: number, payload: UpdateUserPayload): Promise<{ status: string; data: SystemUser }> {
  return request<{ status: string; data: SystemUser }>(`/api/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ─── Account Settings (2026-08-16, self-service -- any logged-in user editing
// their own profile, no admin role required) ───────────────────────────────

export interface UpdateMePayload {
  name?: string;
  email?: string;
  session_timeout_minutes?: number;
  current_password?: string;
  new_password?: string;
}

export function updateMe(payload: UpdateMePayload): Promise<{ status: string; data: SystemUser }> {
  return request<{ status: string; data: SystemUser }>('/api/users/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// ─── Activity Log (2026-08-16, admin-only) ────────────────────────────────

export interface ActivityLogEntry {
  log_id: number;
  user_id: number | null;
  user_name: string | null;
  user_email: string | null;
  action: string;
  endpoint: string;
  summary: string;
  // Full sentence of what was done (2026-10-22); null only for older entries.
  remarks: string | null;
  status_code: number;
  created_at: string | null;
}

// Filters run server-side (2026-10-22) so a narrowed view reaches past the
// newest `limit` rows. actionType is one of ActivityLogFilters.action_types.
export function getActivityLog(
  filters: { userId?: number; actionType?: string; limit?: number } = {},
): Promise<{ status: string; data: ActivityLogEntry[] }> {
  const params = new URLSearchParams();
  if (filters.userId !== undefined) params.set('user_id', String(filters.userId));
  if (filters.actionType) params.set('action_type', filters.actionType);
  if (filters.limit !== undefined) params.set('limit', String(filters.limit));
  const query = params.toString();
  return request<{ status: string; data: ActivityLogEntry[] }>(`/api/activity-log/${query ? `?${query}` : ''}`);
}

export interface ActivityLogFilters {
  users: { user_id: number; name: string; email: string; role: string }[];
  action_types: string[];
}

export function getActivityLogFilters(): Promise<{ status: string; data: ActivityLogFilters }> {
  return request<{ status: string; data: ActivityLogFilters }>('/api/activity-log/filters');
}

// "Verify Farm Planted" (2026-10-12) -- pre-event Sentinel-1 VV/VH colour layer
// over a typhoon's affected farms (same set as the Spatial Analysis "Affected
// by" filter). An optional overlay beside the automatic planted check below.
export interface SarLayer {
  tile_url: string;
  scene_dates: string[];
  relative_orbit: number;
  window_start: string;
  window_end: string;
  min_db: number;
  max_db: number;
  palette: string[];
  typhoon_id: number;
  event_date: string;
  farm_count: number;
  capped: boolean;
  skipped_no_geom: number;
}

export function getSarLayer(typhoonId: number): Promise<{ status: string; data: SarLayer }> {
  return request<{ status: string; data: SarLayer }>('/api/sar/layer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ typhoon_id: typhoonId }),
  });
}

// Automatic planted check (2026-10-12, docs/SAR_ISPLANTED_METHOD.md §3) --
// every affected farm GREEN "planted" or YELLOW "field_verify", stored per
// typhoon. Replaces the Specialist's manual Planted / Not planted buttons in
// the UI; like them, never read by the assessment or the PABS export.
export type PlantedCheckStatus = 'planted' | 'field_verify';

export interface PlantedCheckResult {
  farm_id: number;
  status: PlantedCheckStatus;
  reason_code: string;
  reason: string;
  t0_date: string | null;
  tp_date: string | null;
  vh_rise_db: number | null;
  ratio_drop_db: number | null;
  relative_orbit: number | null;
  scene_count: number;
}

export interface PlantedCheckSummary {
  typhoon_id: number;
  window_start: string;
  window_end: string;
  checked_at: string | null;
  checked: number;
  planted: number;
  field_verify: number;
  reasons: { code: string; label: string; count: number }[];
  // Only on a fresh run (POST): farms pulled from Earth Engine vs. read
  // from the stored series.
  fetched_from_gee?: number;
  from_cache?: number;
}

export interface PlantedCheckData {
  summary: PlantedCheckSummary | null;
  results: PlantedCheckResult[];
}

export function runPlantedCheck(typhoonId: number): Promise<{ status: string; data: PlantedCheckData }> {
  return request<{ status: string; data: PlantedCheckData }>('/api/sar/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ typhoon_id: typhoonId }),
  });
}

export function getPlantedChecks(typhoonId: number): Promise<{ status: string; data: PlantedCheckData }> {
  return request<{ status: string; data: PlantedCheckData }>(`/api/sar/checks?typhoon_id=${typhoonId}`);
}

// Field verification list (2026-10-13) -- a typhoon's YELLOW "field_verify"
// farms with farmer, policy and location, for Assessment & Reporting's
// preview + CSV. Only farms eligible for insurance on the typhoon (with a
// computed assessment for it), not every affected farm SAR checked. Read-only: unlike the PABS export, nothing gets locked.
// Keys match the CSV headers (backend FIELD_VERIFY_CSV_HEADERS).
export interface FieldVerifyRow {
  farm_id: number;
  FARMER_NAME: string | null;
  FARMERID: string | null;
  FARMID: string | null;
  CIC_NO: string | null;
  PROVINCE: string | null;
  MUNICIPALITY: string | null;
  BARANGAY: string | null;
  AREA: number | null;
  TYPHOON_NAME: string | null;
  SAR_REASON: string;
}

export interface FieldVerifyList {
  typhoon_id: number;
  typhoon_name: string;
  // Farms the planted check covered; 0 = never run for this typhoon.
  checked: number;
  // Farms with a computed assessment for this typhoon; 0 = Compute
  // Assessments not run yet.
  assessed: number;
  checked_at: string | null;
  rows: FieldVerifyRow[];
}

export function getFieldVerifyList(typhoonId: number): Promise<{ status: string; data: FieldVerifyList }> {
  return request<{ status: string; data: FieldVerifyList }>(`/api/sar/field-verify?typhoon_id=${typhoonId}`);
}

export function downloadFieldVerifyCsv(typhoonId: number): Promise<void> {
  return downloadCsv(`/api/sar/field-verify/export?typhoon_id=${typhoonId}`,
                     `sar_field_verification_typhoon_${typhoonId}.csv`);
}

// ─── Admin Panel settings (2026-10-22) ──────────────────────────────────────
// Backs CalibrationModule.tsx -- see backend/app/api/settings.py. The coverage
// rate is the DEFAULT Amount of Cover (₱/ha x farm area) applied at upload only
// to records with no AmountofCover; CSV values always win.
export interface SystemSettings {
  coverage_rate_per_ha: number;
  coverage_rate_min: number;
  coverage_rate_max: number;
  auto_backup_enabled: boolean;
}

export function getSystemSettings(): Promise<{ status: string; data: SystemSettings }> {
  return request<{ status: string; data: SystemSettings }>('/api/settings');
}

export function updateCoverageRate(rate: number): Promise<{ status: string; data: SystemSettings }> {
  return request<{ status: string; data: SystemSettings }>('/api/settings/coverage-rate', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ coverage_rate_per_ha: rate }),
  });
}

export function updateAutoBackup(enabled: boolean): Promise<{ status: string; data: SystemSettings }> {
  return request<{ status: string; data: SystemSettings }>('/api/settings/auto-backup', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}

// Read-only: the real two-step PCIC lookup the payout engine uses.
export interface RecsapMatrixRow {
  crop_stage_no: number;
  crop_stage: string;
  wind_signal_tcws: number;
  exposure_hours: number;
  estimated_yield_loss: number;
}

export interface IndemnityMatrixRow {
  crop_stage_group: string;
  yield_loss_min: number;
  yield_loss_max: number;
  indemnity_factor: number;
}

export interface PcicMatrices {
  recsap: RecsapMatrixRow[];
  indemnity: IndemnityMatrixRow[];
}

export function getPcicMatrices(): Promise<{ status: string; data: PcicMatrices }> {
  return request<{ status: string; data: PcicMatrices }>('/api/settings/matrices');
}

// ─── Database Backup & Archive (2026-10-22) ─────────────────────────────────
// See backend/app/api/archives.py. Archive & Clear is open to every signed-in
// user; everything else here is admin-only. Archives are read-only.
export interface ArchiveTyphoon {
  typhoon_id: number;
  name: string;
  year: number;
  last_bulletin_at: string | null;
  clear_after: string | null;
}

export interface ArchiveEligibility {
  eligible: boolean;
  reason: string | null;
  eligible_at: string | null;
  clear_after_days: number;
  counts: { farmers: number; farms: number; policies: number; assessments: number };
  typhoons: ArchiveTyphoon[];
  label: string;
  archive_configured: boolean;
  confirm_word: string;
}

export interface ArchiveResult {
  archive_id: number;
  label: string;
  row_counts: Record<string, number>;
  record_count: number;
  dump_file_name: string;
  gdrive_uploaded: boolean;
  gdrive_error: string | null;
}

export interface ArchiveBatch {
  archive_id: number;
  label: string;
  typhoons: ArchiveTyphoon[];
  archived_at: string;
  archived_by_name: string | null;
  row_counts: Record<string, number>;
  record_count: number;
  dump_file_name: string | null;
  gdrive_file_id: string | null;
}

export interface ArchiveRecord {
  insurance_records_id: number;
  farm_id: number | null;
  farmers_id: string | null;
  farmer_name: string | null;
  farm_reference: string | null;
  province: string | null;
  municipality: string | null;
  barangay: string | null;
  area_size: number | null;
  policy_no: string | null;
  program_type: string | null;
  effectivity_date: string | null;
  expiry_date: string | null;
  amount_cover: number | null;
  typhoon_name: string | null;
  typhoon_year: number | null;
  wind_signal: number | null;
  crop_stage: string | null;
  period_of_exposure: number | null;
  wind_velocity: number | null;
  indemnity_factor: number | null;
  estimated_damage: number | null;
  final_indemnity_payment: number | null;
  assessment_date: string | null;
}

export interface ArchiveRecordsPage {
  total: number;
  page: number;
  page_size: number;
  rows: ArchiveRecord[];
}

export interface ArchiveFarmProperties {
  farm_id: number;
  municipality: string | null;
  barangay: string | null;
  area_size: number | null;
  csv_farm_reference: string | null;
  farmer_name: string | null;
  total_payout: number;
}

export interface ArchiveFarmsCollection {
  type: 'FeatureCollection';
  features: Array<{ type: 'Feature'; geometry: GeoJsonMultiPolygon; properties: ArchiveFarmProperties }>;
  truncated: boolean;
  // [west, south, east, north] of every farm in the archive.
  extent: [number, number, number, number] | null;
}

export interface ArchiveExposureProperties {
  kind: 'exposure' | 'track';
  typhoon_id: number;
  typhoon_name: string | null;
  typhoon_year: number | null;
  province?: string;
  municipality?: string;
  max_signal_level?: number;
  total_exposure_hours?: number;
}

export interface ArchiveExposureCollection {
  type: 'FeatureCollection';
  features: Array<{ type: 'Feature'; geometry: { type: string; coordinates: unknown }; properties: ArchiveExposureProperties }>;
}

export interface BackupEntry {
  backup_id: number;
  kind: 'manual' | 'scheduled' | 'archive';
  file_name: string | null;
  size_bytes: number | null;
  status: 'success' | 'failed';
  error: string | null;
  gdrive_uploaded: boolean;
  gdrive_error: string | null;
  created_at: string;
  file_available: boolean;
}

export interface BackupOverview {
  backups: BackupEntry[];
  last_backup: BackupEntry | null;
  stored_count: number;
  gdrive_configured: boolean;
  archive_configured: boolean;
}

export function getArchiveEligibility(): Promise<{ status: string; data: ArchiveEligibility }> {
  return request<{ status: string; data: ArchiveEligibility }>('/api/archives/eligibility');
}

export function archiveAndClear(confirm: string): Promise<{ status: string; data: ArchiveResult }> {
  return request<{ status: string; data: ArchiveResult }>('/api/archives', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm }),
  });
}

export function getArchives(): Promise<{ status: string; data: ArchiveBatch[] }> {
  return request<{ status: string; data: ArchiveBatch[] }>('/api/archives');
}

export function getArchiveRecords(archiveId: number, q: string, page: number, pageSize = 50): Promise<{ status: string; data: ArchiveRecordsPage }> {
  const params = new URLSearchParams({ q, page: String(page), page_size: String(pageSize) });
  return request<{ status: string; data: ArchiveRecordsPage }>(`/api/archives/${archiveId}/records?${params}`);
}

export function getArchiveFarms(archiveId: number, bbox?: [number, number, number, number]): Promise<ArchiveFarmsCollection> {
  const query = bbox ? `?bbox=${bbox.map(v => v.toFixed(5)).join(',')}` : '';
  return request<ArchiveFarmsCollection>(`/api/archives/${archiveId}/farms${query}`);
}

export function getArchiveExposure(archiveId: number): Promise<ArchiveExposureCollection> {
  return request<ArchiveExposureCollection>(`/api/archives/${archiveId}/exposure`);
}

export function downloadArchiveCsv(archiveId: number): Promise<void> {
  return downloadCsv(`/api/archives/${archiveId}/export`, `archive_${archiveId}.csv`);
}

// Assessment & Reporting's archived typhoons (Admin + GIS Specialist, read-only).
export interface ArchivedTyphoon {
  typhoon_id: number;
  name: string;
  year: number;
  archive_id: number;
  label: string;
  archived_at: string;
}

export interface ArchivedTyphoonRows {
  archive_id: number;
  label: string;
  archived_at: string;
  // Same shape as getAssessmentsPabsSummary()'s rows.
  rows: PabsAssessmentRow[];
}

export function getArchivedTyphoons(): Promise<{ status: string; data: ArchivedTyphoon[] }> {
  return request<{ status: string; data: ArchivedTyphoon[] }>('/api/archives/typhoons');
}

export function getArchivedTyphoonRows(typhoonId: number): Promise<{ status: string; data: ArchivedTyphoonRows }> {
  return request<{ status: string; data: ArchivedTyphoonRows }>(`/api/archives/typhoon/${typhoonId}/pabs-rows`);
}

export function getBackups(): Promise<{ status: string; data: BackupOverview }> {
  return request<{ status: string; data: BackupOverview }>('/api/backups');
}

export function runBackupNow(): Promise<{ status: string; data: BackupEntry }> {
  return request<{ status: string; data: BackupEntry }>('/api/backups', { method: 'POST' });
}

// Same authenticated blob-download path as the CSV exports, just a .dump file.
export function downloadBackup(backup: BackupEntry): Promise<void> {
  return downloadCsv(`/api/backups/${backup.backup_id}/download`, backup.file_name ?? `backup_${backup.backup_id}.dump`);
}
