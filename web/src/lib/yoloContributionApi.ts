import { getSupabaseBrowser } from './supabaseBrowser';
import { mapBlindWorkspace, mapRevealResult, type BlindWorkspace, type HumanAnnotation, type RevealResult } from './yoloContribution';

async function headers(json = false): Promise<HeadersInit> {
  const { data } = await getSupabaseBrowser().auth.getSession();
  const value: Record<string, string> = {};
  if (data.session) value.Authorization = `Bearer ${data.session.access_token}`;
  if (json) value['Content-Type'] = 'application/json';
  return value;
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await fetch(path, init);
  const payload: unknown = await response.json();
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? String((payload as { detail: unknown }).detail)
      : '게코 박스 요청을 완료하지 못했어.';
    throw new Error(detail);
  }
  return payload;
}

export async function getYoloWorkspace(): Promise<BlindWorkspace> {
  const payload = await request('/api/yolo-contributions/workspace', { headers: await headers() });
  if (typeof payload !== 'object' || payload === null || !('workspace' in payload)) throw new Error('작업 응답이 올바르지 않아.');
  return mapBlindWorkspace((payload as { workspace: unknown }).workspace);
}

export async function submitYoloBlind(taskId: string, annotation: HumanAnnotation): Promise<void> {
  await request(`/api/yolo-contributions/tasks/${taskId}/blind`, {
    method: 'POST', headers: await headers(true), body: JSON.stringify(annotation),
  });
}

export async function revealYoloPrediction(taskId: string): Promise<RevealResult> {
  return mapRevealResult(await request(`/api/yolo-contributions/tasks/${taskId}/reveal`, {
    method: 'POST', headers: await headers(),
  }));
}

export async function submitYoloRevision(taskId: string, annotation: HumanAnnotation, reason: string): Promise<void> {
  await request(`/api/yolo-contributions/tasks/${taskId}/revision`, {
    method: 'POST', headers: await headers(true), body: JSON.stringify({ ...annotation, reason }),
  });
}
