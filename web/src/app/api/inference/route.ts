import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { classifyClip, VLM_MODEL_ID } from '@/lib/gemini';
import { buildSystemPrompt } from '@/lib/prompts';
import { DB_SPECIES_TO_CODE, isBehaviorClass, SPECIES_CLASSES, type Species } from '@/types';

// 라운드 1 기본 종 — pet_id NULL 클립 (직접 촬영/유튜브 보충 영상)에 적용
const DEFAULT_SPECIES: Species = 'crested_gecko';

export const maxDuration = 300; // 클립당 5-15초 × 다수 → 5분까지 허용 (Vercel hint, 로컬은 영향 없음)

interface Result {
  clip_id: string;
  ok: boolean;
  action?: string;
  confidence?: number;
  error?: string;
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body || !Array.isArray(body.clip_ids) || body.clip_ids.length === 0) {
    return NextResponse.json({ error: 'clip_ids 필수' }, { status: 400 });
  }
  const clipIds = body.clip_ids as string[];

  // 클립 + pet 종 nested select (Supabase JS의 PostgREST embedding)
  const { data: clips, error } = await supabaseAdmin
    .from('camera_clips')
    .select('id, file_path, pet_id, pets:pet_id(species_id)')
    .in('id', clipIds);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const results: Result[] = [];

  // 직렬 처리. Gemini Free tier rate ~15 RPM, 여유롭게.
  // 라운드 2~ 병렬화는 클립 5개씩 chunk Promise.all.
  for (const c of clips ?? []) {
    try {
      // species 결정 — pet 있으면 그쪽, 없으면 라운드 1 기본
      const pet = (c as { pets?: { species_id?: string | null } | null }).pets;
      const dbSpeciesId = pet?.species_id ?? null;
      const species: Species = dbSpeciesId
        ? (DB_SPECIES_TO_CODE[dbSpeciesId] ?? DEFAULT_SPECIES)
        : DEFAULT_SPECIES;

      const systemPrompt = await buildSystemPrompt(species);
      const r = await classifyClip({ videoPath: c.file_path, systemPrompt });

      let { action, confidence, reasoning } = r;

      // 8클래스 검증
      if (!isBehaviorClass(action)) {
        results.push({ clip_id: c.id, ok: false, error: `잘못된 클래스: ${action}` });
        continue;
      }
      // 종 가용성 검증 (예: leopard에 eating_paste 응답)
      if (!SPECIES_CLASSES[species].includes(action)) {
        confidence = 0;
        reasoning = `[VALIDATION] species mismatch (${action} unavailable for ${species}). ${reasoning}`;
      }

      const { error: insErr } = await supabaseAdmin.from('behavior_logs').insert({
        clip_id: c.id,
        frame_idx: 0,
        action,
        confidence,
        source: 'vlm',
        vlm_model: VLM_MODEL_ID,
        reasoning,
        verified: false,
      });
      if (insErr) {
        results.push({ clip_id: c.id, ok: false, error: `DB: ${insErr.message}` });
        continue;
      }
      results.push({ clip_id: c.id, ok: true, action, confidence });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      results.push({ clip_id: c.id, ok: false, error: msg });
    }
  }

  revalidatePath('/');
  revalidatePath('/inference');
  revalidatePath('/results');
  return NextResponse.json({ results });
}
