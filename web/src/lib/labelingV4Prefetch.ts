// v4 다음 영상 프리페치(UX ②, 2026-09-08) — 상세가 열리면 "같은 카메라의 다음 안 된 영상"의 메타·서명 URL·GME
// overlay 를 미리 받아 두고, 확정 뒤 이동할 때 캐시로 즉시 그린다(로딩 화면 생략). 영상 바이트도 숨은 <video> 로
// 미리 버퍼링해 브라우저 캐시를 데운다.
//
// 계약:
// - 캐시는 clip 당 1개, 꺼내면 지운다(takePrefetched). 서명 URL 은 만료 30초 전부터 무효로 본다(그땐 url 만 null).
// - 프리페치 실패는 조용히 무시한다 — 정상 경로(load)가 그대로 동작해야 한다.
// - 어떤 clip 이 "다음"인지는 이동 시점에 서버에 다시 묻는다(그 사이 남이 확정했을 수 있음). 캐시는 id 가 같을 때만 쓰인다.
'use client';

import type { GmeOverlayResponse } from './gmeOverlay';
import type { V4ClipDetail } from './labelingV4';

export interface PrefetchedClip {
  detail: V4ClipDetail;
  fileUrl: string | null;
  fileExpiresAt: number; // epoch ms, fileUrl 이 null 이면 0
  overlay: GmeOverlayResponse | null;
}

export interface PrefetchApi {
  getV4Clip: (clipId: string) => Promise<V4ClipDetail>;
  getV4FileUrl: (clipId: string) => Promise<{ url: string; expires_in: number }>;
  getV4GmeOverlay: (clipId: string) => Promise<GmeOverlayResponse>;
}

const FILE_URL_SAFETY_MS = 30_000;
const MAX_CACHE = 4;

const cache = new Map<string, PrefetchedClip>();
const inflight = new Map<string, Promise<void>>();
// 숨은 <video> 참조 — GC 되면 버퍼링이 멈추므로 잠깐 붙잡는다(최근 2개).
const warmVideos = new Map<string, HTMLVideoElement>();

export function isPrefetched(clipId: string): boolean {
  return cache.has(clipId);
}

// 지우지 않고 본다. 서명 URL 이 만료 근처면 url 만 null 로 돌려 호출자가 새로 받게 한다.
// 왜 안 지우나: React StrictMode(dev)가 mount 효과를 두 번 돌리고, 같은 clip 을 뒤로가기로 다시 열 수도 있다.
// 소비자는 최신 메타를 받은 뒤 dropPrefetched 로 지운다.
export function peekPrefetched(clipId: string, now = Date.now()): PrefetchedClip | null {
  const hit = cache.get(clipId);
  if (!hit) return null;
  if (hit.fileUrl && now >= hit.fileExpiresAt) return { ...hit, fileUrl: null, fileExpiresAt: 0 };
  return hit;
}

export function dropPrefetched(clipId: string): void {
  cache.delete(clipId);
}

// peek + drop (테스트·일회성 소비용).
export function takePrefetched(clipId: string, now = Date.now()): PrefetchedClip | null {
  const hit = peekPrefetched(clipId, now);
  if (hit) cache.delete(clipId);
  return hit;
}

export async function prefetchClip(clipId: string, api: PrefetchApi, now = Date.now()): Promise<void> {
  if (cache.has(clipId)) return;
  const running = inflight.get(clipId);
  if (running) return running;
  const task = (async () => {
    try {
      const detail = await api.getV4Clip(clipId);
      const [file, overlay] = await Promise.all([
        detail.media_ready ? api.getV4FileUrl(clipId).catch(() => null) : Promise.resolve(null),
        api.getV4GmeOverlay(clipId).catch(() => null),
      ]);
      // 오래된 항목부터 버린다(뒤로가기 등으로 여러 clip 이 쌓이는 경우).
      while (cache.size >= MAX_CACHE) {
        const oldest = cache.keys().next().value;
        if (oldest === undefined) break;
        cache.delete(oldest);
      }
      cache.set(clipId, {
        detail,
        fileUrl: file?.url ?? null,
        fileExpiresAt: file ? now + Math.max(0, file.expires_in * 1000 - FILE_URL_SAFETY_MS) : 0,
        overlay,
      });
    } catch {
      // 프리페치는 최선 노력 — 실패해도 정상 로드가 처리한다.
    } finally {
      inflight.delete(clipId);
    }
  })();
  inflight.set(clipId, task);
  return task;
}

// 영상 바이트 예열 — 같은 서명 URL 을 실제 플레이어가 쓰므로 브라우저 캐시/버퍼가 이어진다.
export function warmVideo(clipId: string, url: string): void {
  if (typeof document === 'undefined' || warmVideos.has(clipId)) return;
  try {
    const v = document.createElement('video');
    v.preload = 'auto';
    v.muted = true;
    v.setAttribute('referrerpolicy', 'no-referrer');
    v.src = url;
    v.load();
    warmVideos.set(clipId, v);
    while (warmVideos.size > 2) {
      const oldest = warmVideos.keys().next().value;
      if (oldest === undefined) break;
      const old = warmVideos.get(oldest);
      if (old) old.removeAttribute('src');
      warmVideos.delete(oldest);
    }
  } catch {
    // 예열 실패는 무시.
  }
}

// 테스트용.
export function _resetPrefetchCache(): void {
  cache.clear();
  inflight.clear();
  warmVideos.clear();
}
