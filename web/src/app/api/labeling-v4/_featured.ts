import { readGmeActiveContract } from '@/lib/labelingV3Server';
import { FEATURED_DAY_CAP, FEATURED_DAY_START_HOUR, FEATURED_GAP_SEC, FEATURED_HOUR_CAP, FEATURED_MAX_DAYS, FEATURED_TOP_N, FEATURED_TZ, type V4ClipItem, type V4FeaturedInfo } from '@/lib/labelingV4';
import { dayKeyOf, dayKeyStartUtc, featuredWindowFor, mapFeaturedInfo, type V4FeaturedRow } from '@/lib/labelingV4Server';
import { supabaseAdmin } from '@/lib/supabase';

const DAY_MS = 86_400_000;

// ⭐ 대표 tier — fn_highlight_featured 호출부 단일화. 저장된 값이 아니라 조회 시 계산(스펙 §4.1).
export async function loadFeaturedRows(args: { cameraIds: string[] | null; from: string; to: string; topN?: number | null }): Promise<V4FeaturedRow[]> {
  const contract = readGmeActiveContract();
  const { data, error } = await supabaseAdmin.rpc('fn_highlight_featured', {
    p_camera_ids: args.cameraIds,
    p_from: args.from,
    p_to: args.to,
    p_engine_schema_version: contract.engine_schema_version,
    p_algorithm_version: contract.algorithm_version,
    p_detector_identity: contract.detector_identity,
    p_top_n: args.topN === undefined ? FEATURED_TOP_N : args.topN, // null = 하루 상한 없음
    p_gap_sec: FEATURED_GAP_SEC,
    p_day_start_hour: FEATURED_DAY_START_HOUR,
    p_tz: FEATURED_TZ,
    p_hour_cap: FEATURED_HOUR_CAP,
    p_day_cap: FEATURED_DAY_CAP,
  });
  if (error) throw error;
  return (data ?? []) as V4FeaturedRow[];
}

// 목록 페이지의 현재-O 항목에 tier 를 붙인다. 보조 정보 — 실패·31일 초과 창이면 전부 null(목록은 계속).
export async function attachFeatured(items: V4ClipItem[]): Promise<void> {
  const targets = items.filter((i) => i.highlight.status === 'decided' && i.highlight.value === true);
  if (targets.length === 0) return;
  const win = featuredWindowFor(targets.map((i) => i.started_at));
  if (!win || Date.parse(win.to) - Date.parse(win.from) > FEATURED_MAX_DAYS * DAY_MS) return;
  const cams = Array.from(new Set(targets.map((i) => i.camera_id).filter((c): c is string => typeof c === 'string')));
  try {
    const rows = await loadFeaturedRows({ cameraIds: cams.length ? cams : null, from: win.from, to: win.to });
    const byId = new Map(rows.map((r) => [String(r.clip_id), mapFeaturedInfo(r, FEATURED_TOP_N)] as const));
    for (const it of targets) it.featured = byId.get(it.id) ?? null;
  } catch {
    // 보조 정보 — 조회 실패해도 목록은 그대로.
  }
}

// 상세: 그 클립의 하루 창 하나로 tier 를 찾는다. O 가 아니면 호출하지 않는다.
export async function loadFeaturedForClip(clip: { id: string; camera_id: string | null; started_at: string }, isCurrentO: boolean): Promise<V4FeaturedInfo | null> {
  if (!isCurrentO || !clip.camera_id) return null;
  const from = dayKeyStartUtc(dayKeyOf(clip.started_at));
  const to = new Date(from.getTime() + DAY_MS);
  try {
    const rows = await loadFeaturedRows({ cameraIds: [clip.camera_id], from: from.toISOString(), to: to.toISOString() });
    const row = rows.find((r) => r.clip_id === clip.id);
    return row ? mapFeaturedInfo(row, FEATURED_TOP_N) : null;
  } catch {
    return null;
  }
}
