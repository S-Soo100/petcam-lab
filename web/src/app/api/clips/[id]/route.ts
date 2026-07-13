import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { deleteObject } from '@/lib/r2';
import { loadClipWithPerms } from '@/lib/clipPerms';

// DELETE /api/clips/[id]
// 클립 영구 삭제 — owner-only.
//
// 삭제 순서 (가장 사이드이펙트 큰 거부터):
//  1. R2 mp4 + thumbnail (best-effort — 실패해도 DB 진행. orphan R2 는 lifecycle/수동 청소)
//  2. behavior_labels (FK CASCADE 가 있을 수 있지만 명시 삭제로 안전)
//  3. behavior_logs (동일)
//  4. camera_clips (마지막)
//
// 왜 R2 먼저?
// - DB row 가 사라진 뒤 R2 만 남으면 영원히 추적 불가.
// - R2 가 사라진 뒤 DB row 만 남으면 사용자가 보고 다시 삭제 시도 가능.
// - 즉, 큰 사이드이펙트(외부 시스템) 부터 처리.
//
// 권한 모델:
// - service_role 라우트라 토큰 검증을 직접 함 (RLS 우회 클라이언트라).
// - Bearer token → Supabase Auth getUser → user.id === DEV_USER_ID 매치.
// - /api/poc/summary 와 동일 패턴.

export const runtime = 'nodejs';

// GET /api/clips/[id]
// 클립 메타 단건 조회 — 라벨링 승인 사용자 전용.
export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const clipId = params.id;
  if (!clipId) {
    return NextResponse.json({ detail: 'clip id missing' }, { status: 400 });
  }
  const result = await loadClipWithPerms(req, clipId);
  if (!result.ok) return result.response;
  return NextResponse.json(result.access.clip);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const auth = req.headers.get('authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const {
    data: { user },
    error: authErr,
  } = await supabaseAdmin.auth.getUser(token);
  if (authErr || !user) {
    return NextResponse.json({ error: 'invalid token' }, { status: 401 });
  }

  const devUserId = process.env.DEV_USER_ID;
  if (!devUserId) {
    return NextResponse.json({ error: 'DEV_USER_ID 누락' }, { status: 500 });
  }
  if (user.id !== devUserId) {
    return NextResponse.json({ error: 'forbidden — owner only' }, { status: 403 });
  }

  const clipId = params.id;
  if (!clipId) {
    return NextResponse.json({ error: 'clip id 누락' }, { status: 400 });
  }

  // 1) clip 조회 (r2_key + thumbnail_r2_key 가 있으면 R2 도 청소)
  const { data: clip, error: selErr } = await supabaseAdmin
    .from('camera_clips')
    .select('id, user_id, r2_key, thumbnail_r2_key')
    .eq('id', clipId)
    .single();
  if (selErr || !clip) {
    return NextResponse.json({ error: 'clip not found' }, { status: 404 });
  }
  // 본인 소유 clip 만 — 미러 등 우회 방지.
  if (clip.user_id !== devUserId) {
    return NextResponse.json({ error: 'forbidden — not your clip' }, { status: 403 });
  }

  // 2) R2 삭제 (best-effort, 실패해도 진행)
  const r2Errors: string[] = [];
  if (clip.r2_key) {
    try {
      await deleteObject(clip.r2_key);
    } catch (e) {
      r2Errors.push(`mp4(${clip.r2_key}): ${(e as Error).message}`);
    }
  }
  if (clip.thumbnail_r2_key) {
    try {
      await deleteObject(clip.thumbnail_r2_key);
    } catch (e) {
      r2Errors.push(`thumb(${clip.thumbnail_r2_key}): ${(e as Error).message}`);
    }
  }

  // 3) behavior_labels — 신 라벨 테이블. row 없을 수 있음 (라벨 안 된 클립).
  const { error: labErr } = await supabaseAdmin
    .from('behavior_labels')
    .delete()
    .eq('clip_id', clipId);
  if (labErr) {
    return NextResponse.json(
      { error: `behavior_labels 삭제 실패: ${labErr.message}`, r2_errors: r2Errors },
      { status: 500 },
    );
  }

  // 4) behavior_logs — 구 라벨 + VLM 추론 결과 모두 포함.
  const { error: logErr } = await supabaseAdmin
    .from('behavior_logs')
    .delete()
    .eq('clip_id', clipId);
  if (logErr) {
    return NextResponse.json(
      { error: `behavior_logs 삭제 실패: ${logErr.message}`, r2_errors: r2Errors },
      { status: 500 },
    );
  }

  // 5) camera_clips — 마지막. FK 가 child 에 걸려있어도 위에서 다 비웠으니 안전.
  const { error: clipErr } = await supabaseAdmin
    .from('camera_clips')
    .delete()
    .eq('id', clipId);
  if (clipErr) {
    return NextResponse.json(
      { error: `camera_clips 삭제 실패: ${clipErr.message}`, r2_errors: r2Errors },
      { status: 500 },
    );
  }

  revalidatePath('/');
  revalidatePath('/queue');
  revalidatePath('/labeling');
  revalidatePath('/results');

  return NextResponse.json(
    {
      ok: true,
      clip_id: clipId,
      r2_errors: r2Errors.length > 0 ? r2Errors : undefined,
    },
    { status: 200 },
  );
}
