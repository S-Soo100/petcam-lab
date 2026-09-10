import { presignGet } from '@/lib/r2';
import { supabaseAdmin } from '@/lib/supabase';

const THUMBNAIL_TTL_SEC = 600;

// 카드 썸네일(UX ⑦): motion_clips.thumbnail_key 를 한 번에 조회해 짧은 서명 URL 로 붙인다. 실패는 null(목록은 계속).
// clips route 와 featured route 가 공유한다.
export async function attachThumbnails(items: { id: string; thumbnail_url: string | null }[]): Promise<void> {
  if (items.length === 0) return;
  try {
    const { data, error } = await supabaseAdmin.from('motion_clips').select('id, thumbnail_key').in('id', items.map((i) => i.id));
    if (error) throw error;
    const keys = new Map<string, string>();
    for (const row of (data ?? []) as { id?: unknown; thumbnail_key?: unknown }[]) {
      if (typeof row.id === 'string' && typeof row.thumbnail_key === 'string' && row.thumbnail_key) keys.set(row.id, row.thumbnail_key);
    }
    await Promise.all(items.map(async (it) => {
      const key = keys.get(it.id);
      if (!key) return;
      try { it.thumbnail_url = await presignGet(key, THUMBNAIL_TTL_SEC); } catch { it.thumbnail_url = null; }
    }));
  } catch {
    // 썸네일은 보조 정보 — 조회 실패해도 목록은 그대로 돌려준다.
  }
}
