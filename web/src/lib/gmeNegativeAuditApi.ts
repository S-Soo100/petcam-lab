'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { mapAuditDetailRow, mapAuditQueueRow, validateAuditSubmission } from './gmeNegativeAudit';
import type {
  AuditCorrection,
  AuditDetailItem,
  AuditQueueResponse,
  AuditSubmission,
  AuditVerdict,
  NormalizedBox,
} from './gmeNegativeAudit';
import { getSupabaseBrowser } from './supabaseBrowser';

async function authHeader(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await getSupabaseBrowser().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function invalidResponse(): never {
  throw new ApiError(502, '서버 응답이 올바르지 않아.', undefined, 'invalid_response');
}

function requireExactRecord(
  value: unknown,
  keys: readonly string[],
): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) invalidResponse();
  const row = value as Record<string, unknown>;
  const actual = Object.keys(row).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    invalidResponse();
  }
  return row;
}

function safeCount(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) invalidResponse();
  return value;
}

async function request<T>(
  path: string,
  validate: (value: unknown) => T,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
    ...(await authHeader()),
  };
  if (init?.body) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, cache: 'no-store' });
  } catch (error) {
    throw new ApiError(0, `네트워크 오류: ${(error as Error).message}`);
  }
  if (response.status === 401) throw new UnauthorizedError();
  if (!response.ok) {
    let detail = response.statusText || `HTTP ${response.status}`;
    let code: string | undefined;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      if (typeof body?.code === 'string') code = body.code;
    } catch {
      // JSON이 아닌 오류는 HTTP status text만 사용한다.
    }
    throw new ApiError(response.status, detail, undefined, code);
  }
  const mediaType = response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
  if (mediaType !== 'application/json') invalidResponse();
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    invalidResponse();
  }
  try {
    return validate(body);
  } catch (error) {
    if (error instanceof ApiError && error.code === 'invalid_response') throw error;
    invalidResponse();
  }
}

function itemPath(itemId: string): string {
  return `/api/labeling-v3/gme-audit/${encodeURIComponent(itemId)}`;
}

export function getAuditQueue(): Promise<AuditQueueResponse> {
  return request('/api/labeling-v3/gme-audit/queue', validateQueueResponse);
}

export function getAuditItem(itemId: string): Promise<AuditDetailItem> {
  return request(itemPath(itemId), validateDetailResponse);
}

export interface AuditMediaResponse {
  url: string;
  expires_in: number;
}

export function getAuditMedia(itemId: string): Promise<AuditMediaResponse> {
  return request(`${itemPath(itemId)}/file/url`, validateMediaResponse);
}

export function submitAudit(
  itemId: string,
  submission: AuditSubmission,
): Promise<{ status: 'submitted' }> {
  return request(
    `${itemPath(itemId)}/submit`,
    (value) => validateStatusResponse(value, 'submitted'),
    {
      method: 'POST',
      body: JSON.stringify(submission),
    },
  );
}

export function correctAudit(
  itemId: string,
  correction: AuditCorrection,
): Promise<{ status: 'corrected' }> {
  return request(
    `${itemPath(itemId)}/correct`,
    (value) => validateStatusResponse(value, 'corrected'),
    {
      method: 'POST',
      body: JSON.stringify(correction),
    },
  );
}

export type AuditOwnerStratum = 'random_negative' | 'positive_control';

export interface AuditOwnerPendingItem {
  item_id: string;
  ordinal: number;
  duration_sec: number;
  stratum: AuditOwnerStratum;
  effective_verdict: AuditVerdict;
  effective_representative_sec: number | null;
  effective_bbox: NormalizedBox | null;
  expected_submission_digest: string;
}

export interface AuditOwnerDatasetItem {
  item_id: string;
  ordinal: number;
  duration_sec: number;
  stratum: 'random_negative';
  effective_verdict: AuditVerdict;
  effective_representative_sec: number | null;
  effective_bbox: NormalizedBox | null;
  expected_effective_digest: string;
}

export interface AuditOwnerProgress {
  completed: number;
  total: number;
}

export interface AuditOwnerOverview {
  batch_id: string;
  batch_state: 'opened';
  completed: number;
  total: number;
  random_negative: AuditOwnerProgress;
  positive_control: AuditOwnerProgress;
  needs_adjudication: AuditOwnerPendingItem[];
  dataset_decision_eligible: AuditOwnerDatasetItem[];
}

export interface AuditOwnerAdjudication {
  final_verdict: AuditVerdict;
  representative_sec: number | null;
  bbox: NormalizedBox | null;
  reason: string;
  expected_submission_digest: string;
}

export type AuditDatasetDecision =
  | 'include_candidate'
  | 'exclude_duplicate'
  | 'exclude_holdout'
  | 'exclude_quality'
  | 'defer';

export interface AuditDatasetDecisionRequest {
  decision: AuditDatasetDecision;
  reason: string;
  expected_effective_digest: string;
}

export function getAuditOwnerOverview(): Promise<AuditOwnerOverview> {
  return request('/api/labeling-v3/gme-audit/owner/overview', validateOwnerOverview);
}

export function getAuditOwnerMedia(itemId: string): Promise<AuditMediaResponse> {
  const expectedPath = `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(itemId)}/file`;
  return request(
    `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(itemId)}/file/url`,
    (value) => validateOwnerMediaResponse(value, expectedPath),
  );
}

export function adjudicateAuditItem(
  itemId: string,
  adjudication: AuditOwnerAdjudication,
): Promise<{ status: 'adjudicated'; effective_digest: string }> {
  return request(
    `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(itemId)}/adjudicate`,
    validateAdjudicationResponse,
    { method: 'POST', body: JSON.stringify(adjudication) },
  );
}

export function decideAuditDatasetMembership(
  itemId: string,
  decision: AuditDatasetDecisionRequest,
): Promise<{ status: 'decided' }> {
  return request(
    `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(itemId)}/dataset-decision`,
    (value) => validateStatusResponse(value, 'decided'),
    { method: 'POST', body: JSON.stringify(decision) },
  );
}

const QUEUE_ITEM_KEYS = [
  'captured_at',
  'duration_sec',
  'item_id',
  'media_ready',
  'ordinal',
  'submitted',
] as const;
const DETAIL_KEYS = [
  'captured_at',
  'duration_sec',
  'effective_bbox',
  'effective_representative_sec',
  'effective_verdict',
  'initial_bbox',
  'initial_representative_sec',
  'initial_verdict',
  'item_id',
  'media_ready',
  'ordinal',
  'revision',
] as const;

function validateQueueResponse(value: unknown): AuditQueueResponse {
  const row = requireExactRecord(value, ['completed', 'items', 'total']);
  if (!Array.isArray(row.items)) invalidResponse();
  const completed = safeCount(row.completed);
  const total = safeCount(row.total);
  if (completed > total) invalidResponse();
  const items = row.items.map((item) => {
    const itemRow = requireExactRecord(item, QUEUE_ITEM_KEYS);
    if (typeof itemRow.duration_sec !== 'number') invalidResponse();
    return mapAuditQueueRow(item);
  });
  return { items, completed, total };
}

function validateDetailResponse(value: unknown): AuditDetailItem {
  const row = requireExactRecord(value, DETAIL_KEYS);
  if (typeof row.duration_sec !== 'number') invalidResponse();
  for (const key of ['initial_representative_sec', 'effective_representative_sec'] as const) {
    if (row[key] !== null && typeof row[key] !== 'number') invalidResponse();
  }
  return mapAuditDetailRow(value);
}

function validateMediaResponse(value: unknown): AuditMediaResponse {
  const row = requireExactRecord(value, ['expires_in', 'url']);
  if (typeof row.url !== 'string') invalidResponse();
  let url: URL;
  try {
    url = new URL(row.url);
  } catch {
    invalidResponse();
  }
  if (url.protocol !== 'https:') invalidResponse();
  const expiresIn = safeCount(row.expires_in);
  if (expiresIn < 1 || expiresIn > 3_600) invalidResponse();
  return { url: row.url, expires_in: expiresIn };
}

function validateOwnerMediaResponse(value: unknown, expectedPath: string): AuditMediaResponse {
  const row = requireExactRecord(value, ['expires_in', 'url']);
  if (row.url !== expectedPath) invalidResponse();
  const expiresIn = safeCount(row.expires_in);
  if (expiresIn < 1 || expiresIn > 3_600) invalidResponse();
  return { url: expectedPath, expires_in: expiresIn };
}

function validateStatusResponse<T extends 'submitted' | 'corrected' | 'decided'>(
  value: unknown,
  expected: T,
): { status: T } {
  const row = requireExactRecord(value, ['status']);
  if (row.status !== expected) invalidResponse();
  return { status: expected };
}

const OWNER_ITEM_KEYS = [
  'duration_sec',
  'effective_bbox',
  'effective_representative_sec',
  'effective_verdict',
  'expected_submission_digest',
  'item_id',
  'ordinal',
  'stratum',
] as const;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256 = /^[0-9a-f]{64}$/;

function validateOwnerProgress(value: unknown): AuditOwnerProgress {
  const row = requireExactRecord(value, ['completed', 'total']);
  const completed = safeCount(row.completed);
  const total = safeCount(row.total);
  if (completed > total) invalidResponse();
  return { completed, total };
}

function validateOwnerOverview(value: unknown): AuditOwnerOverview {
  const row = requireExactRecord(value, [
    'batch_id', 'batch_state', 'completed', 'dataset_decision_eligible', 'needs_adjudication',
    'positive_control', 'random_negative', 'total',
  ]);
  if (typeof row.batch_id !== 'string' || !UUID.test(row.batch_id)) invalidResponse();
  if (row.batch_state !== 'opened') invalidResponse();
  const completed = safeCount(row.completed);
  const total = safeCount(row.total);
  if (
    completed > total || !Array.isArray(row.needs_adjudication) ||
    !Array.isArray(row.dataset_decision_eligible)
  ) invalidResponse();
  const randomNegative = validateOwnerProgress(row.random_negative);
  const positiveControl = validateOwnerProgress(row.positive_control);
  if (
    randomNegative.total + positiveControl.total !== total ||
    randomNegative.completed + positiveControl.completed !== completed
  ) invalidResponse();
  const seen = new Set<string>();
  const needsAdjudication = row.needs_adjudication.map((value) => {
    const item = requireExactRecord(value, OWNER_ITEM_KEYS);
    if (typeof item.item_id !== 'string' || !UUID.test(item.item_id) || seen.has(item.item_id)) invalidResponse();
    seen.add(item.item_id);
    const ordinal = safeCount(item.ordinal);
    if (ordinal < 1 || typeof item.duration_sec !== 'number' || !Number.isFinite(item.duration_sec) || item.duration_sec <= 0) invalidResponse();
    if (item.stratum !== 'random_negative' && item.stratum !== 'positive_control') invalidResponse();
    const stratum: AuditOwnerStratum = item.stratum;
    if (typeof item.expected_submission_digest !== 'string' || !SHA256.test(item.expected_submission_digest)) invalidResponse();
    const effective = validateAuditSubmission({
      verdict: item.effective_verdict,
      representative_sec: item.effective_representative_sec,
      bbox: item.effective_bbox,
    }, item.duration_sec);
    return {
      item_id: item.item_id,
      ordinal,
      duration_sec: item.duration_sec,
      stratum,
      effective_verdict: effective.verdict,
      effective_representative_sec: effective.representative_sec,
      effective_bbox: effective.bbox,
      expected_submission_digest: item.expected_submission_digest,
    };
  });
  const datasetDecisionEligible = row.dataset_decision_eligible.map((value) => {
    const item = requireExactRecord(value, [
      'duration_sec', 'effective_bbox', 'effective_representative_sec', 'effective_verdict',
      'expected_effective_digest', 'item_id', 'ordinal', 'stratum',
    ]);
    if (
      typeof item.item_id !== 'string' || !UUID.test(item.item_id) || seen.has(item.item_id) ||
      item.stratum !== 'random_negative'
    ) invalidResponse();
    seen.add(item.item_id);
    const ordinal = safeCount(item.ordinal);
    if (
      ordinal < 1 || typeof item.duration_sec !== 'number' ||
      !Number.isFinite(item.duration_sec) || item.duration_sec <= 0 ||
      typeof item.expected_effective_digest !== 'string' || !SHA256.test(item.expected_effective_digest)
    ) invalidResponse();
    const effective = validateAuditSubmission({
      verdict: item.effective_verdict,
      representative_sec: item.effective_representative_sec,
      bbox: item.effective_bbox,
    }, item.duration_sec);
    return {
      item_id: item.item_id,
      ordinal,
      duration_sec: item.duration_sec,
      stratum: 'random_negative' as const,
      effective_verdict: effective.verdict,
      effective_representative_sec: effective.representative_sec,
      effective_bbox: effective.bbox,
      expected_effective_digest: item.expected_effective_digest,
    };
  });
  return {
    batch_id: row.batch_id,
    batch_state: 'opened',
    completed,
    total,
    random_negative: randomNegative,
    positive_control: positiveControl,
    needs_adjudication: needsAdjudication,
    dataset_decision_eligible: datasetDecisionEligible,
  };
}

function validateAdjudicationResponse(value: unknown): { status: 'adjudicated'; effective_digest: string } {
  const row = requireExactRecord(value, ['effective_digest', 'status']);
  if (row.status !== 'adjudicated' || typeof row.effective_digest !== 'string' || !SHA256.test(row.effective_digest)) invalidResponse();
  return { status: 'adjudicated', effective_digest: row.effective_digest };
}
