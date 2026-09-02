'use client';

import { ApiError, UnauthorizedError } from './labelingApi';
import type {
  OwnerCleanupDecision,
  OwnerCleanupWorkspace,
} from './rbaOwnerMediaCleanup';
import { getSupabaseBrowser } from './supabaseBrowser';

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await getSupabaseBrowser().auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(await authHeader()),
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (init?.body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) throw new UnauthorizedError();
  if (!response.ok) {
    let detail = '요청을 처리하지 못했어.';
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // 공개 일반 문구 유지.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function getOwnerCleanupWorkspace(): Promise<OwnerCleanupWorkspace> {
  return request('/api/labeling-v3/owner-media-cleanup');
}

export function getOwnerCleanupMediaUrl(
  clipId: string,
  download = false,
): Promise<{ url: string; expires_in: number; filename?: string }> {
  return request(
    `/api/labeling-v3/owner-media-cleanup/${clipId}/file/url${download ? '?download=1' : ''}`,
  );
}

export function decideOwnerCleanup(
  clipId: string,
  decision: OwnerCleanupDecision,
): Promise<{ ok: true }> {
  return request(`/api/labeling-v3/owner-media-cleanup/${clipId}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision }),
  });
}
