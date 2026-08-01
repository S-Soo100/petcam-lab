'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import { getSupabaseBrowser } from './supabaseBrowser';
import type {
  BoundaryConflicts,
  BoundaryDecision,
  BoundaryEligibilityDecision,
  BoundaryWorkspace,
  LabelingDataDashboard,
} from './rbaBoundaryServer';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { data: { session } } = await getSupabaseBrowser().auth.getSession();
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
    ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
  };
  if (init?.body) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (cause) {
    throw new ApiError(0, `네트워크 오류: ${(cause as Error).message}`);
  }
  if (response.status === 401) throw new UnauthorizedError();
  if (!response.ok) {
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch { /* status text 사용 */ }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function getLabelingDashboard(): Promise<LabelingDataDashboard> {
  return request('/api/labeling-dashboard');
}

export async function getBoundaryWorkspace(): Promise<BoundaryWorkspace> {
  return (await request<{ workspace: BoundaryWorkspace }>('/api/rba-boundary/workspace')).workspace;
}

export function getBoundaryMediaUrl(
  pairId: string,
  side: 'left' | 'right',
): Promise<{ url: string; expires_in: number }> {
  return request(`/api/rba-boundary/pairs/${encodeURIComponent(pairId)}/file/url?side=${side}`);
}

export function submitBoundaryDecision(pairId: string, decision: BoundaryDecision) {
  return request(`/api/rba-boundary/pairs/${encodeURIComponent(pairId)}/submit`, {
    method: 'POST', body: JSON.stringify({ decision }),
  });
}

export function submitBoundaryEligibility(
  pairId: string,
  decision: BoundaryEligibilityDecision,
) {
  return request(`/api/rba-boundary/pairs/${encodeURIComponent(pairId)}/eligibility`, {
    method: 'POST', body: JSON.stringify({ decision }),
  });
}

export function getBoundaryConflicts(): Promise<BoundaryConflicts> {
  return request('/api/rba-boundary/conflicts');
}

export function resolveBoundaryConflict(
  pairId: string,
  finalDecision: BoundaryDecision,
  reason: string,
) {
  return request(`/api/rba-boundary/conflicts/${encodeURIComponent(pairId)}/resolve`, {
    method: 'POST', body: JSON.stringify({ final_decision: finalDecision, reason }),
  });
}
