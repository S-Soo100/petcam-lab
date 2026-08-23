'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { mapAuditDetailRow, mapAuditQueueRow } from './gmeNegativeAudit';
import type {
  AuditCorrection,
  AuditDetailItem,
  AuditQueueResponse,
  AuditSubmission,
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

function validateStatusResponse<T extends 'submitted' | 'corrected'>(
  value: unknown,
  expected: T,
): { status: T } {
  const row = requireExactRecord(value, ['status']);
  if (row.status !== expected) invalidResponse();
  return { status: expected };
}
