'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
  return response.json() as Promise<T>;
}

function itemPath(itemId: string): string {
  return `/api/labeling-v3/gme-audit/${encodeURIComponent(itemId)}`;
}

export function getAuditQueue(): Promise<AuditQueueResponse> {
  return request<AuditQueueResponse>('/api/labeling-v3/gme-audit/queue');
}

export function getAuditItem(itemId: string): Promise<AuditDetailItem> {
  return request<AuditDetailItem>(itemPath(itemId));
}

export interface AuditMediaResponse {
  url: string;
  expires_in: number;
}

export function getAuditMedia(itemId: string): Promise<AuditMediaResponse> {
  return request<AuditMediaResponse>(`${itemPath(itemId)}/file/url`);
}

export function submitAudit(
  itemId: string,
  submission: AuditSubmission,
): Promise<{ status: 'submitted' }> {
  return request<{ status: 'submitted' }>(`${itemPath(itemId)}/submit`, {
    method: 'POST',
    body: JSON.stringify(submission),
  });
}

export function correctAudit(
  itemId: string,
  correction: AuditCorrection,
): Promise<{ status: 'corrected' }> {
  return request<{ status: 'corrected' }>(`${itemPath(itemId)}/correct`, {
    method: 'POST',
    body: JSON.stringify(correction),
  });
}
