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
  location_geom: GeoJsonMultiPolygon | null;
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

export interface UploadCsvResult {
  status: string;
  message: string;
  rows_processed: number;
  rows_inserted: number;
  rows_skipped: number;
}

export interface ParseBulletinsResult {
  status: string;
  parsed_count: number;
  bulletins: Array<{ tcb_id: number; title: string; bulletin_count: number }>;
}

export interface TcbSignal {
  signal_id: number;
  signal_level: number;
  island_group: number;
  area_name: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function uploadCsv(file: File): Promise<UploadCsvResult> {
  const formData = new FormData();
  formData.append('file', file);
  return request<UploadCsvResult>('/api/upload/csv', {
    method: 'POST',
    body: formData,
  });
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

export function getFarms(): Promise<{ status: string; data: Farm[] }> {
  return request<{ status: string; data: Farm[] }>('/api/farms/');
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
