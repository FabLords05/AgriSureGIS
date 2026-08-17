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
  policy_no: string | null;
  effectivity_date: string | null;
  expiry_date: string | null;
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
// farms with a currently-active InsuranceRecord, and `municipality` to
// restrict to one AdminBoundary.municipality -- see useFarmsData.ts and
// SpatialAnalysisModule.tsx.
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
}): Promise<GetFarmsResult> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.after_id != null) query.set('after_id', String(params.after_id));
  if (params?.active_only != null) query.set('active_only', String(params.active_only));
  if (params?.municipality) query.set('municipality', params.municipality);
  const qs = query.toString();
  return request<GetFarmsResult>(`/api/farms/${qs ? `?${qs}` : ''}`);
}

// Viewport-scoped polygon fetch backing GISLeafletMap.tsx -- pass `bbox`
// ("minLon,minLat,maxLon,maxLat") for the normal moveend/zoomend case, or
// `farm_id` (which ignores bbox/active_only/municipality server-side) to
// resolve one specific farm's geometry regardless of the map's current
// viewport/filters -- e.g. FlyToSelectedFarm's out-of-view case. See
// backend/app/api/farms.py's get_farms_geometry docstring.
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
  active_only?: boolean;
  municipality?: string;
}): Promise<GetFarmsGeometryResult> {
  const query = new URLSearchParams();
  if (params.bbox) query.set('bbox', params.bbox);
  if (params.farm_id != null) query.set('farm_id', String(params.farm_id));
  if (params.active_only != null) query.set('active_only', String(params.active_only));
  if (params.municipality) query.set('municipality', params.municipality);
  return request<GetFarmsGeometryResult>(`/api/farms/geometry?${query.toString()}`);
}

// Distinct municipality names for the Farm Records search box's suggestion
// list -- sourced from AdminBoundary, not from whatever farms happen to be
// loaded, so it's populated even before any municipality has been searched.
// See backend/app/api/farms.py's list_farm_municipalities docstring.
export function getMunicipalities(): Promise<{ status: string; data: string[] }> {
  return request<{ status: string; data: string[] }>('/api/farms/municipalities');
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

export function getAssessmentsExportUrl(typhoonId: number): string {
  return `${API_BASE_URL}/api/assessments/export?typhoon_id=${typhoonId}`;
}

// Combined export across every typhoon (not scoped to one bulletin/typhoon
// folder), in the PABS-required column format. IRID/P/S columns come back
// blank -- no definition for them was available; see the backend docstring.
export function getAssessmentsExportPabsUrl(): string {
  return `${API_BASE_URL}/api/assessments/export-pabs`;
}

export interface PabsAssessmentRow {
  assessment_id: number;
  FARMER_NAME: string | null;
  FARMERID: string | null;
  FARMID: number | null;
  IRID: null;
  AREA: number | null;
  TYPHOON_NAME: string | null;
  PERIOD_OF_EXPOSURE: number | null;
  WIND_VELOCITY: number | null;
  DATE_FILED: string | null;
  DATE_OF_OCCURRENCE: string | null;
  P: null;
  S: null;
  AC: number | null;
  REMARKS: null;
  municipality: string | null;
  province: string | null;
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
  user_name: string | null;
  user_email: string | null;
  action: string;
  endpoint: string;
  summary: string;
  status_code: number;
  created_at: string | null;
}

export function getActivityLog(): Promise<{ status: string; data: ActivityLogEntry[] }> {
  return request<{ status: string; data: ActivityLogEntry[] }>('/api/activity-log/');
}
